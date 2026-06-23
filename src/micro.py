import pyaudio
import webrtcvad
import numpy as np
import requests
import os
import time
import wave
import json
import urllib.request
from pathlib import Path
from openwakeword.model import Model
import luces
import config

DEEPGRAM_API_KEY = config.DEEPGRAM_API_KEY
WAKE_MODEL = config.WAKE_MODEL_PATH

SAMPLE_RATE = 16000
OWW_FRAME = 1280                # 80 ms — frame nativo de openWakeWord
VAD_FRAME_MS = 20               # webrtcvad acepta 10/20/30 ms
VAD_FRAME = SAMPLE_RATE * VAD_FRAME_MS // 1000  # 320 samples a 16kHz
WAKE_THRESHOLD = 0.3
SILENCE_MS_TO_STOP = 400
MIN_VOICE_MS = 300
MAX_UTTERANCE_MS = 8000

_pa = None
_stream = None
_oww = None
_vad = None
_capture_rate = SAMPLE_RATE   # sample rate real del hardware (puede ser 48000 si el device no soporta 16k)

GANANCIA_MIC = 8.0  # ajustable: probar 3.0 / 4.0 / 6.0 / 8.0 según qué tan bajo capture el HW

# #region debug-point D:micro-runtime
_DEBUG_ENV_PATH = Path(__file__).resolve().parent.parent / ".dbg" / "unexpected-process-exit.env"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"


def _json_safe(value):
    """Convierte tipos de numpy a tipos nativos para que el logger no rompa."""
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _debug_emit(msg: str, data: dict | None = None):
    payload = {
        "sessionId": "unexpected-process-exit",
        "runId": "pre-fix",
        "hypothesisId": "D",
        "location": "micro.py",
        "msg": f"[DEBUG] {msg}",
        "data": data or {},
        "ts": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False, default=_json_safe)
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


def _amplificar(audio_bytes, factor=GANANCIA_MIC):
    """Aplica ganancia digital al audio PCM16 y satura (clip) para evitar overflow."""
    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    audio = audio * factor
    audio = np.clip(audio, -32768, 32767).astype(np.int16)
    return audio.tobytes()


def _encontrar_dispositivo():
    # Orden de preferencia: I2S (INMP441 vía dtoverlay), USB, Google VoiceHAT, cualquier otro.
    preferidos = ("i2s", "snd_rpi_simple", "snd-i2s", "inmp441",
                  "usb", "voicehat", "googlevoice", "snd_rpi_google")
    candidatos = []
    for i in range(_pa.get_device_count()):
        info = _pa.get_device_info_by_index(i)
        if info['maxInputChannels'] <= 0:
            continue
        nombre_low = info['name'].lower()
        for prio, clave in enumerate(preferidos):
            if clave in nombre_low:
                candidatos.append((prio, i, info['name']))
                break
        else:
            # Cualquier input no-matched queda como fallback
            candidatos.append((99, i, info['name']))
    if not candidatos:
        print("⚠️ Ningún dispositivo de entrada detectado. Usando default.")
        return None
    candidatos.sort()
    prio, idx, nombre = candidatos[0]
    print(f"🎤 Micro detectado: [{idx}] {nombre}")
    _debug_emit("input-device-selected", {"index": idx, "name": nombre, "priority": prio})
    return idx


def _abrir_stream(idx):
    """Intenta abrir el stream a 16k; si el HW no lo soporta (VoiceHAT, etc.), cae a 48k."""
    global _capture_rate
    for rate in (16000, 48000):
        try:
            buffer_frames = OWW_FRAME * rate // SAMPLE_RATE
            stream = _pa.open(
                rate=rate, channels=1, format=pyaudio.paInt16,
                input=True, frames_per_buffer=buffer_frames,
                input_device_index=idx,
            )
            _capture_rate = rate
            if rate != SAMPLE_RATE:
                print(f"🎤 Micro abierto a {rate} Hz (resample a {SAMPLE_RATE} Hz activo)")
            else:
                print(f"🎤 Micro abierto a {rate} Hz")
            _debug_emit("input-stream-opened", {"device_index": idx, "capture_rate": rate, "target_rate": SAMPLE_RATE})
            return stream
        except OSError as e:
            print(f"   · rate {rate} no soportado ({e}); probando otro…")
            _debug_emit("input-stream-open-failed", {"device_index": idx, "rate": rate, "error": str(e)})
    raise RuntimeError("Ningún sample rate funciona con este micro")


def _leer_raw(samples_16k):
    """Devuelve bytes PCM16 equivalentes a `samples_16k` muestras a 16 kHz, haciendo decimación si el HW captura a mayor rate."""
    factor = _capture_rate // SAMPLE_RATE
    raw = _stream.read(samples_16k * factor, exception_on_overflow=False)
    if factor == 1:
        return _amplificar(raw)
    audio = np.frombuffer(raw, dtype=np.int16)[::factor]
    return _amplificar(audio.tobytes())


def inicializar():
    global _pa, _stream, _oww, _vad
    print("🦻 Cargando openWakeWord...")
    _debug_emit("micro-init-start", {"wake_model": WAKE_MODEL})
    _oww = Model(wakeword_models=[WAKE_MODEL], inference_framework="onnx")
    _vad = webrtcvad.Vad(2)
    _pa = pyaudio.PyAudio()
    _stream = _abrir_stream(_encontrar_dispositivo())
    print("✅ Micro en modo radar: escuchando wake word.")
    _debug_emit("micro-init-end")


def _esperar_wake():
    _oww.reset()
    _ultimo_log = 0.0
    while True:
        raw = _leer_raw(OWW_FRAME)
        audio = np.frombuffer(raw, dtype=np.int16)
        scores = _oww.predict(audio)
        mejor = max(scores.values())
        # Log agresivo de scores para diagnóstico
        if mejor > 0.05 and abs(mejor - _ultimo_log) > 0.02:
            print(f"   🔍 score wake={mejor:.3f} (threshold {WAKE_THRESHOLD})")
            _ultimo_log = mejor
        if mejor > WAKE_THRESHOLD:
            _debug_emit("wake-detected", {"score": float(round(mejor, 4)), "threshold": float(WAKE_THRESHOLD)})
            return


def _esperar_voz(timeout_ms):
    """Espera hasta que se detecte voz. Devuelve el primer frame con voz o None si pasa el timeout."""
    ms_esperados = 0
    while ms_esperados < timeout_ms:
        frame = _leer_raw(VAD_FRAME)
        if _vad.is_speech(frame, SAMPLE_RATE):
            return frame
        ms_esperados += VAD_FRAME_MS
    return None


def _grabar_desde(frame_inicial=b""):
    """Graba con VAD. Opcionalmente arranca con un frame ya capturado."""
    luces.cambiar_estado("escuchando")
    buffer_audio = bytearray(frame_inicial)
    silencio_ms = 0
    voz_ms = VAD_FRAME_MS if frame_inicial else 0
    inicio = time.time()

    while True:
        frame = _leer_raw(VAD_FRAME)
        buffer_audio += frame

        if _vad.is_speech(frame, SAMPLE_RATE):
            voz_ms += VAD_FRAME_MS
            silencio_ms = 0
        else:
            silencio_ms += VAD_FRAME_MS

        if voz_ms >= MIN_VOICE_MS and silencio_ms >= SILENCE_MS_TO_STOP:
            break
        if (time.time() - inicio) * 1000 > MAX_UTTERANCE_MS:
            break

    path = "/dev/shm/grabacion.wav"
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(bytes(buffer_audio))
    _debug_emit("voice-recorded", {"path": path, "bytes": len(buffer_audio), "voice_ms": voz_ms, "silence_ms": silencio_ms})
    return path


def _transcribir_deepgram(path):
    url = "https://api.deepgram.com/v1/listen?model=nova-3&language=es&smart_format=true"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/wav",
    }
    try:
        with open(path, "rb") as audio:
            response = requests.post(url, headers=headers, data=audio, timeout=10)

        if os.path.exists(path):
            os.remove(path)

        if response.status_code == 200:
            transcript = response.json()['results']['channels'][0]['alternatives'][0]['transcript']
            _debug_emit("deepgram-ok", {"status": response.status_code, "transcript_preview": transcript[:160]})
            return transcript
        print(f"⚠️ Error Deepgram: {response.status_code}")
        _debug_emit("deepgram-failed", {"status": response.status_code, "body_preview": response.text[:200]})
        return ""
    except Exception as e:
        print(f"⚠️ Error de conexión: {e}")
        _debug_emit("deepgram-exception", {"error": str(e)})
        return ""


def escuchar():
    """Espera wake word, graba y transcribe. Usar al inicio de cada conversación."""
    print("💤 En reposo. Di la wake word para despertarme...")
    _debug_emit("listen-radar-start")
    _esperar_wake()
    print("🎤 [Wake] ¡Despierto! Escuchando tu petición...")
    wav = _grabar_desde()
    print("🧠 [Deepgram] Analizando...")
    _debug_emit("listen-radar-audio-ready", {"wav_path": wav})
    return _transcribir_deepgram(wav)


def escuchar_seguimiento(timeout_ms=8000):
    """Escucha sin wake word, con timeout. Devuelve None si no se detecta voz en `timeout_ms`."""
    print(f"👂 ¿Algo más? ({timeout_ms//1000}s)...")
    luces.cambiar_estado("escuchando")
    frame = _esperar_voz(timeout_ms)
    if frame is None:
        print("⌛ Silencio. Volviendo al modo radar.")
        _debug_emit("followup-timeout", {"timeout_ms": timeout_ms})
        return None
    print("🎤 Voz captada, grabando...")
    wav = _grabar_desde(frame)
    print("🧠 [Deepgram] Analizando...")
    _debug_emit("followup-audio-ready", {"wav_path": wav, "timeout_ms": timeout_ms})
    return _transcribir_deepgram(wav)


def cerrar():
    global _stream, _pa
    if _stream:
        try:
            _stream.stop_stream()
            _stream.close()
        except Exception:
            pass
        _stream = None
    if _pa:
        try:
            _pa.terminate()
        except Exception:
            pass
        _pa = None
    _debug_emit("micro-closed")
