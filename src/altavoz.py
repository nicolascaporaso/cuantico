import requests
import subprocess
import luces
import config

ELEVENLABS_API_KEY = config.ELEVENLABS_API_KEY
VOICE_ID = config.ELEVENLABS_VOICE_ID
TTS_MODEL = "eleven_turbo_v2_5"  # ~250ms TTFB, calidad cercana al multilingual


def _lanzar_mpg123():
    """
    Pipeline: MP3 → sox (filtros para altavocito pequeño) → aplay.
    - highpass 300: elimina graves que el altavoz no puede reproducir
    - bass -4:     recorta un pelín más los 100Hz residuales
    - treble +2:   da un toque de presencia
    - gain -n:     normaliza volumen
    """
    sox_proc = subprocess.Popen(
        ["sox", "-q", "-t", "mp3", "-", "-t", "wav", "-",
         "highpass", "300",
         "bass", "-4",
         "treble", "+2",
         "gain", "-n", "-5"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    aplay_proc = subprocess.Popen(
        ["aplay", "-q", "-D", "default"],
        stdin=sox_proc.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sox_proc.stdout.close()
    # Devolvemos un objeto con stdin y wait() compuesto
    class Pipeline:
        def __init__(self, a, b):
            self._a = a
            self._b = b
            self.stdin = a.stdin
        def wait(self):
            self._a.wait()
            self._b.wait()
    return Pipeline(sox_proc, aplay_proc)


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
    r = requests.post(url, json=data, headers=headers, stream=True)
    if r.status_code != 200:
        print(f"⚠️ ElevenLabs {r.status_code}: {r.text[:120]}")
        return
    for chunk in r.iter_content(chunk_size=2048):
        if chunk:
            try:
                stdin.write(chunk)
                stdin.flush()
            except BrokenPipeError:
                return


def _encontrar_corte(buffer):
    """Devuelve índice del final de la primera frase, o -1 si no hay."""
    candidatos = []
    for p in [". ", "! ", "? ", ".\n", "!\n", "?\n", "\n"]:
        i = buffer.find(p)
        if i != -1:
            candidatos.append(i + len(p) - 1)
    return min(candidatos) if candidatos else -1


def hablar(texto, emocion):
    """Reproduce un texto completo (sin streaming de generación)."""
    luces.cambiar_estado(emocion)
    print(f"🔊 [Altavoz] Escupiendo audio ({emocion})...")
    proceso = _lanzar_mpg123()
    try:
        _tts_a_tuberia(texto, proceso.stdin)
    finally:
        try:
            proceso.stdin.close()
        except Exception:
            pass
        proceso.wait()


def hablar_stream(generador_texto, emocion="sarcasmo"):
    """
    Recibe un generador de strings (chunks de Gemini).
    Va troceando en frases y mandándolas a ElevenLabs según llegan.
    → La primera frase empieza a sonar antes de que Gemini termine.
    """
    luces.cambiar_estado(emocion)
    print(f"🔊 [Altavoz] Streaming paralelo ({emocion})...")
    proceso = _lanzar_mpg123()
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
        # Restos finales
        if buffer.strip():
            _tts_a_tuberia(buffer.strip(), proceso.stdin)
    finally:
        try:
            proceso.stdin.close()
        except Exception:
            pass
        proceso.wait()
