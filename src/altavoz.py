import requests
import subprocess
import time
import json
import threading
import urllib.request
from pathlib import Path
import RPi.GPIO as GPIO
import luces
import config
import bluetooth_audio
from runtime_debug import dump_threads, heartbeat, mark_operation_end, mark_operation_start

ELEVENLABS_API_KEY = config.ELEVENLABS_API_KEY
VOICE_ID = config.ELEVENLABS_VOICE_ID
TTS_MODEL = "eleven_turbo_v2_5"  # ~250ms TTFB, calidad cercana al multilingual
STARTUP_WAV_PATH = Path(__file__).resolve().parent.parent / "test.wav"
# Pon esto a False si en el futuro quieres desactivar el WAV de arranque.
ENABLE_STARTUP_WAV = True

# La Google VoiceHAT muta el ampli por hardware vía GPIO16 para evitar que el
# parlante retroalimente al micro mientras el sistema escucha. Hay que
# desmutear antes de reproducir y volver a mutear al terminar.
PIN_MUTE_SPEAKER = 16
_gpio_listo = False

# #region debug-point B:audio-runtime
_DEBUG_ENV_PATH = Path(__file__).resolve().parent.parent / ".dbg" / "unexpected-process-exit.env"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"
_SOX_STDERR_PATH = Path(config.STATE_DIR) / "tts-sox.log"
_APLAY_STDERR_PATH = Path(config.STATE_DIR) / "tts-aplay.log"
_tts_lock = threading.Lock()


def _debug_emit(msg: str, data: dict | None = None):
    payload = {
        "sessionId": "unexpected-process-exit",
        "runId": "pre-fix",
        "hypothesisId": "B",
        "location": "altavoz.py",
        "msg": f"[DEBUG] {msg}",
        "data": data or {},
        "ts": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        debug_url = "http://127.0.0.1:7777/event"
        if _DEBUG_ENV_PATH.exists():
            for env_line in _DEBUG_ENV_PATH.read_text(encoding="utf-8").splitlines():
                if env_line.startswith("DEBUG_SERVER_URL="):
                    debug_url = env_line.split("=", 1)[1].strip()
        req = urllib.request.Request(debug_url, data=line.encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=0.8).read()
    except Exception:
        pass
# #endregion


def _asegurar_gpio():
    global _gpio_listo
    if _gpio_listo:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(PIN_MUTE_SPEAKER, GPIO.OUT)
    GPIO.output(PIN_MUTE_SPEAKER, GPIO.LOW)  # arranca muteado
    _gpio_listo = True


def _desmutear():
    _asegurar_gpio()
    GPIO.output(PIN_MUTE_SPEAKER, GPIO.HIGH)
    _debug_emit("speaker-unmuted", {"pin": PIN_MUTE_SPEAKER})


def _mutear():
    _asegurar_gpio()
    GPIO.output(PIN_MUTE_SPEAKER, GPIO.LOW)
    _debug_emit("speaker-muted", {"pin": PIN_MUTE_SPEAKER})


def _resolver_salida():
    """Permite cambiar entre I2S local y Bluetooth sin tocar el resto del TTS."""
    salida = bluetooth_audio.obtener_salida_activa()
    salida.setdefault("device", config.ALSA_PLAYBACK_DEVICE)
    salida.setdefault("label", salida["device"])
    salida.setdefault("needs_gpio", True)
    return salida


def resolver_salida_audio():
    """Expone la ruta de audio actual para otros reproductores del proyecto."""
    salida = _resolver_salida()
    _debug_emit(
        "audio-route-resolved",
        {
            "route_kind": salida.get("kind"),
            "device": salida.get("device"),
            "label": salida.get("label"),
            "needs_gpio": bool(salida.get("needs_gpio")),
        },
    )
    return salida


def activar_salida_audio(salida: dict):
    """Desmutea la salida local cuando el backend de audio lo necesita."""
    if salida.get("needs_gpio"):
        _desmutear()


def desactivar_salida_audio(salida: dict):
    """Vuelve a mutear la salida local cuando termina la reproducción."""
    if salida.get("needs_gpio"):
        _mutear()


def _aplay_cmd(salida: dict):
    """Centraliza el device ALSA para no repetirlo en cada reproducción."""
    return ["aplay", "-q", "-D", salida["device"]]


def _open_process_log(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a", encoding="utf-8", errors="replace")


def _terminate_process(proc: subprocess.Popen, name: str, timeout: float = 2.0):
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
        _debug_emit("audio-process-terminated", {"process": name, "pid": proc.pid, "returncode": proc.returncode})
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)
        _debug_emit("audio-process-killed", {"process": name, "pid": proc.pid, "returncode": proc.returncode})


def _lanzar_mpg123():
    """
    Pipeline: MP3 → sox (filtros para altavocito pequeño) → aplay.
    - highpass 300: elimina graves que el altavoz no puede reproducir
    - bass -4:     recorta un pelín más los 100Hz residuales
    - treble +2:   da un toque de presencia
    - gain -n:     normaliza volumen
    """
    salida = _resolver_salida()
    sox_stderr = _open_process_log(_SOX_STDERR_PATH)
    aplay_stderr = _open_process_log(_APLAY_STDERR_PATH)
    sox_proc = subprocess.Popen(
        ["sox", "-q", "-t", "mp3", "-", "-t", "wav", "-",
         "highpass", "300",
         "bass", "-4",
         "treble", "+2",
         "gain", "-n", "-5"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sox_stderr,
    )
    aplay_proc = subprocess.Popen(
        _aplay_cmd(salida),
        stdin=sox_proc.stdout,
        stdout=subprocess.DEVNULL,
        stderr=aplay_stderr,
    )
    _debug_emit(
        "audio-pipeline-started",
        {
            "device": salida["device"],
            "route_kind": salida["kind"],
            "route_label": salida["label"],
            "sox_pid": sox_proc.pid,
            "aplay_pid": aplay_proc.pid,
        },
    )
    sox_proc.stdout.close()
    # Devolvemos un objeto con stdin y wait() compuesto
    class Pipeline:
        def __init__(self, a, b, route, sox_log, aplay_log):
            self._a = a
            self._b = b
            self.stdin = a.stdin
            self.route = route
            self._sox_log = sox_log
            self._aplay_log = aplay_log

        def _close_logs(self):
            for handle in (self._sox_log, self._aplay_log):
                try:
                    handle.close()
                except Exception:
                    pass

        def terminate(self):
            _terminate_process(self._a, "sox")
            _terminate_process(self._b, "aplay")

        def wait(self, timeout: float = 10.0):
            inicio = time.time()
            try:
                self._a.wait(timeout=timeout)
                restante = max(0.1, timeout - (time.time() - inicio))
                self._b.wait(timeout=restante)
            except subprocess.TimeoutExpired:
                _debug_emit(
                    "audio-pipeline-timeout",
                    {
                        "timeout_sec": timeout,
                        "sox_pid": self._a.pid,
                        "aplay_pid": self._b.pid,
                        "route_kind": self.route["kind"],
                        "route_label": self.route["label"],
                    },
                )
                dump_threads(
                    "audio-pipeline-timeout",
                    {
                        "timeout_sec": timeout,
                        "sox_pid": self._a.pid,
                        "aplay_pid": self._b.pid,
                    },
                )
                self.terminate()
                raise
            finally:
                self._close_logs()

    return Pipeline(sox_proc, aplay_proc, salida, sox_stderr, aplay_stderr)


def _tts_a_tuberia(texto, stdin):
    """Pide audio a ElevenLabs (streaming) y escribe bytes directos a mpg123."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream?output_format=mp3_22050_32"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    data = {
        "text": texto,
        "model_id": TTS_MODEL,
        "language_code": "es",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    request_token = mark_operation_start("elevenlabs-request", {"text_len": len(texto), "voice_id": VOICE_ID})
    heartbeat("tts-request", {"state": "start", "text_len": len(texto)})
    request_started = time.time()
    _debug_emit("elevenlabs-request-start", {"text_len": len(texto), "voice_id": VOICE_ID})
    try:
        r = requests.post(
            url,
            json=data,
            headers=headers,
            stream=True,
            timeout=(10, 30),
        )
    except requests.RequestException as exc:
        duration = round(time.time() - request_started, 3)
        ended = mark_operation_end(request_token, {"ok": False, "error": str(exc), "duration_sec": duration})
        heartbeat("tts-request", {"state": "error", "duration_sec": duration, "error": str(exc)})
        _debug_emit("elevenlabs-request-error", ended or {"error": str(exc), "duration_sec": duration})
        if duration > 20:
            dump_threads("elevenlabs-request-error", {"duration_sec": duration, "error": str(exc)})
        raise
    request_duration = round(time.time() - request_started, 3)
    _debug_emit(
        "elevenlabs-request-returned",
        {"status": r.status_code, "text_len": len(texto), "duration_sec": request_duration},
    )
    _debug_emit("elevenlabs-response", {"status": r.status_code, "text_len": len(texto), "voice_id": VOICE_ID})
    if r.status_code != 200:
        ended = mark_operation_end(
            request_token,
            {"ok": False, "status": r.status_code, "duration_sec": request_duration},
        )
        heartbeat("tts-request", {"state": "http-error", "status": r.status_code, "duration_sec": request_duration})
        _debug_emit("elevenlabs-request-failed", ended or {"status": r.status_code, "duration_sec": request_duration})
        print(f"⚠️ ElevenLabs {r.status_code}: {r.text[:120]}")
        return
    chunks = 0
    first_chunk_logged = False
    stream_started = time.time()
    for chunk in r.iter_content(chunk_size=2048):
        if chunk:
            try:
                if not first_chunk_logged:
                    first_chunk_logged = True
                    first_chunk_delay = round(time.time() - stream_started, 3)
                    _debug_emit(
                        "elevenlabs-first-chunk",
                        {"text_len": len(texto), "delay_sec": first_chunk_delay},
                    )
                    heartbeat("tts-request", {"state": "first-chunk", "delay_sec": first_chunk_delay})
                    if request_duration + first_chunk_delay > 20:
                        dump_threads(
                            "elevenlabs-first-chunk-slow",
                            {
                                "request_duration_sec": request_duration,
                                "first_chunk_delay_sec": first_chunk_delay,
                            },
                        )
                stdin.write(chunk)
                stdin.flush()
                chunks += 1
            except BrokenPipeError:
                ended = mark_operation_end(
                    request_token,
                    {"ok": False, "chunks_sent": chunks, "error": "BrokenPipeError"},
                )
                heartbeat("tts-request", {"state": "broken-pipe", "chunks_sent": chunks})
                _debug_emit("audio-broken-pipe", {"chunks_sent": chunks, "text_preview": texto[:120]})
                if ended:
                    _debug_emit("elevenlabs-request-finished", ended)
                return
    ended = mark_operation_end(
        request_token,
        {"ok": True, "status": r.status_code, "chunks_sent": chunks, "duration_sec": round(time.time() - request_started, 3)},
    )
    heartbeat("tts-request", {"state": "finished", "chunks_sent": chunks})
    _debug_emit("elevenlabs-stream-finished", {"chunks_sent": chunks, "text_preview": texto[:120]})
    if ended:
        _debug_emit("elevenlabs-request-finished", ended)


def _encontrar_corte(buffer):
    """Devuelve índice del final de la primera frase, o -1 si no hay."""
    candidatos = []
    for p in [". ", "! ", "? ", ".\n", "!\n", "?\n", "\n"]:
        i = buffer.find(p)
        if i != -1:
            candidatos.append(i + len(p) - 1)
    return min(candidatos) if candidatos else -1


def reproducir_wav_directo(ruta: str | Path, emocion: str | None = None) -> bool:
    """Reproduce un WAV local directamente por ALSA, sin pasar por TTS."""
    wav_path = Path(ruta)
    if not wav_path.exists():
        print(f"⚠️ WAV no encontrado: {wav_path}")
        return False

    if emocion:
        luces.cambiar_estado(emocion)

    salida = _resolver_salida()
    print(f"🔊 [Altavoz] Reproduciendo WAV directo: {wav_path.name}")
    _debug_emit(
        "wav-playback-start",
        {
            "file": str(wav_path),
            "emotion": emocion,
            "device": salida["device"],
            "route_kind": salida["kind"],
            "route_label": salida["label"],
        },
    )
    activar_salida_audio(salida)
    try:
        subprocess.run(
            [*_aplay_cmd(salida), str(wav_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _debug_emit("wav-playback-ok", {"file": str(wav_path)})
        return True
    except Exception as e:
        print(
            f"⚠️ No se pudo reproducir {wav_path.name} en {salida['device']}: {e}"
        )
        _debug_emit("wav-playback-failed", {"file": str(wav_path), "error": str(e)})
        return False
    finally:
        desactivar_salida_audio(salida)


def reproducir_sonido_arranque() -> bool:
    """Dispara el WAV de prueba una sola vez al arrancar el proceso."""
    if not ENABLE_STARTUP_WAV:
        return False
    return reproducir_wav_directo(STARTUP_WAV_PATH, emocion="cachondeo")


def hablar(texto, emocion):
    """Reproduce un texto completo (sin streaming de generación)."""
    lock_started = time.time()
    token = mark_operation_start("tts-hablar", {"emotion": emocion, "text_len": len(texto)})
    with _tts_lock:
        heartbeat("tts-playback", {"state": "lock-acquired", "mode": "hablar", "emotion": emocion})
        _debug_emit(
            "tts-lock-acquired",
            {
                "thread": threading.current_thread().name,
                "mode": "hablar",
                "wait_sec": round(time.time() - lock_started, 3),
            },
        )
        luces.cambiar_estado(emocion)
        print(f"🔊 [Altavoz] Escupiendo audio ({emocion})...")
        _debug_emit("tts-playback-start", {"emotion": emocion, "text_preview": texto[:160]})
        proceso = _lanzar_mpg123()
        activar_salida_audio(proceso.route)
        try:
            _tts_a_tuberia(texto, proceso.stdin)
        finally:
            try:
                proceso.stdin.close()
            except Exception:
                pass
            wait_info = None
            try:
                proceso.wait(timeout=10.0)
                wait_info = {"ok": True}
            except subprocess.TimeoutExpired as exc:
                wait_info = {"ok": False, "error": str(exc)}
                _debug_emit("tts-playback-wait-timeout", {"emotion": emocion, "error": str(exc)})
            _debug_emit(
                "tts-playback-end",
                {
                    "emotion": emocion,
                    "route_kind": proceso.route["kind"],
                    "route_label": proceso.route["label"],
                },
            )
            if wait_info:
                ended = mark_operation_end(token, wait_info)
                if ended:
                    _debug_emit("tts-playback-finished", ended)
            desactivar_salida_audio(proceso.route)


def hablar_stream(generador_texto, emocion="sarcasmo"):
    """
    Recibe un generador de strings (chunks de Gemini).
    Va troceando en frases y mandándolas a ElevenLabs según llegan.
    → La primera frase empieza a sonar antes de que Gemini termine.
    """
    lock_started = time.time()
    token = mark_operation_start("tts-hablar-stream", {"emotion": emocion})
    with _tts_lock:
        heartbeat("tts-playback", {"state": "lock-acquired", "mode": "stream", "emotion": emocion})
        _debug_emit(
            "tts-lock-acquired",
            {
                "thread": threading.current_thread().name,
                "mode": "stream",
                "wait_sec": round(time.time() - lock_started, 3),
            },
        )
        luces.cambiar_estado(emocion)
        print(f"🔊 [Altavoz] Streaming paralelo ({emocion})...")
        _debug_emit("tts-stream-start", {"emotion": emocion})
        proceso = _lanzar_mpg123()
        activar_salida_audio(proceso.route)
        buffer = ""
        try:
            for chunk in generador_texto:
                if not chunk:
                    continue
                buffer += chunk
                while True:
                    idx = _encontrar_corte(buffer)
                    if idx == -1:
                        break
                    frase = buffer[: idx + 1].strip()
                    buffer = buffer[idx + 1 :]
                    if frase:
                        _tts_a_tuberia(frase, proceso.stdin)
            if buffer.strip():
                _tts_a_tuberia(buffer.strip(), proceso.stdin)
        finally:
            try:
                proceso.stdin.close()
            except Exception:
                pass
            wait_info = None
            try:
                proceso.wait(timeout=10.0)
                wait_info = {"ok": True}
            except subprocess.TimeoutExpired as exc:
                wait_info = {"ok": False, "error": str(exc)}
                _debug_emit("tts-stream-wait-timeout", {"emotion": emocion, "error": str(exc)})
            _debug_emit(
                "tts-stream-end",
                {"emotion": emocion, "route_kind": proceso.route["kind"], "route_label": proceso.route["label"]},
            )
            if wait_info:
                ended = mark_operation_end(token, wait_info)
                if ended:
                    _debug_emit("tts-stream-finished", ended)
            desactivar_salida_audio(proceso.route)
