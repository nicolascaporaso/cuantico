"""Carga centralizada de configuración desde .env.

Todos los módulos del proyecto importan de aquí en vez de hardcodear secretos.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# El código vive en src/, pero .env y state/ están en la raíz del repo.
_RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(_RAIZ / ".env")


def _req(clave: str) -> str:
    valor = os.getenv(clave, "").strip()
    if not valor:
        raise RuntimeError(f"Falta {clave} en .env")
    return valor


def _opt(clave: str, por_defecto: str = "") -> str:
    return os.getenv(clave, por_defecto).strip()


def _ruta(clave: str, por_defecto: str = "") -> str:
    """Rutas relativas se resuelven contra la raíz del repo."""
    v = _opt(clave, por_defecto)
    if not v:
        return ""
    p = Path(v)
    return str(p if p.is_absolute() else (_RAIZ / p).resolve())


# LLM
GEMINI_API_KEY = _req("GEMINI_API_KEY")

# TTS
ELEVENLABS_API_KEY = _req("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = _opt("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

# STT / wake word
DEEPGRAM_API_KEY = _req("DEEPGRAM_API_KEY")
WAKE_MODEL_PATH = _opt("WAKE_MODEL_PATH")

# Casa
GOVEE_API_KEY = _req("GOVEE_API_KEY")

# Música
SPOTIFY_CLIENT_ID = _req("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = _req("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = _opt("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# Google OAuth (Calendar + YouTube comparten Client ID)
GOOGLE_CLIENT_SECRETS_PATH = _ruta("GOOGLE_CLIENT_SECRETS_PATH", "state/google_client.json")
GOOGLE_TOKEN_PATH = _ruta("GOOGLE_TOKEN_PATH", "state/google_token.json")
YOUTUBE_CHANNEL_ID = _opt("YOUTUBE_CHANNEL_ID")

# Directorio de estado persistente (timers, tokens, etc.)
STATE_DIR = str(_RAIZ / "state")
Path(STATE_DIR).mkdir(exist_ok=True)
