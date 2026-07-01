"""Carga centralizada de configuración desde .env.

Todos los módulos del proyecto importan de aquí en vez de hardcodear secretos.
"""
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
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


def _opt_bool(clave: str, por_defecto: bool = False) -> bool:
    valor = os.getenv(clave)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _ruta(clave: str, por_defecto: str = "") -> str:
    """Rutas relativas se resuelven contra la raíz del repo."""
    v = _opt(clave, por_defecto)
    if not v:
        return ""
    p = Path(v)
    return str(p if p.is_absolute() else (_RAIZ / p).resolve())


# LLM
OPENROUTER_API_KEY = _req("OPENROUTER_API_KEY")
OPENROUTER_MODEL = _opt("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_CALL_MODEL = _opt("OPENROUTER_CALL_MODEL", OPENROUTER_MODEL)
OPENROUTER_HTTP_REFERER = _opt("OPENROUTER_HTTP_REFERER")
CUANTICO_PROFILE = _opt("CUANTICO_PROFILE", "argentino")
CUANTICO_TIMEZONE = _opt("CUANTICO_TIMEZONE", "America/Argentina/Buenos_Aires")
USER_SHORT_NAME = _opt("USER_SHORT_NAME", "Nico")
USER_FULL_NAME = _opt("USER_FULL_NAME", "Nicolas")
ALSA_PLAYBACK_DEVICE = _opt("ALSA_PLAYBACK_DEVICE", "plughw:0,0")
BLUETOOTH_SCAN_SECONDS = int(_opt("BLUETOOTH_SCAN_SECONDS", "8"))
BLUETOOTH_AUDIO_PROFILE = _opt("BLUETOOTH_AUDIO_PROFILE", "a2dp")
BLUETOOTH_AUTO_ROUTE = _opt_bool("BLUETOOTH_AUTO_ROUTE", True)

# TTS
ELEVENLABS_API_KEY = _req("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = _opt("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

# STT / wake word
DEEPGRAM_API_KEY = _req("DEEPGRAM_API_KEY")
WAKE_MODEL_PATH = _opt("WAKE_MODEL_PATH")

# Casa
GOVEE_API_KEY = _req("GOVEE_API_KEY")
WIZ_BROADCAST_SPACE = _opt("WIZ_BROADCAST_SPACE")

# Música
SPOTIFY_CLIENT_ID = _opt("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = _opt("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = _opt(
    "SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:8888/callback"
)

SPOTIFY_ENABLED = bool(
    SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
)
MUSIC_BACKEND_DEFAULT = _opt("MUSIC_BACKEND_DEFAULT", "spotify").lower()
YT_DLP_COMMAND = _opt("YT_DLP_COMMAND", "yt-dlp")
MPV_COMMAND = _opt("MPV_COMMAND", "mpv")
YOUTUBE_AUDIO_SEARCH_LIMIT = max(1, int(_opt("YOUTUBE_AUDIO_SEARCH_LIMIT", "5")))
YOUTUBE_PLAYLIST_SEARCH_LIMIT = max(1, int(_opt("YOUTUBE_PLAYLIST_SEARCH_LIMIT", "8")))
MPV_IPC_SOCKET_PATH = _opt("MPV_IPC_SOCKET_PATH", "/tmp/cuantico-mpv.sock")

# Google OAuth (Calendar + YouTube comparten Client ID)
GOOGLE_CLIENT_SECRETS_PATH = _ruta("GOOGLE_CLIENT_SECRETS_PATH", "state/google_client.json")
GOOGLE_TOKEN_PATH = _ruta("GOOGLE_TOKEN_PATH", "state/google_token.json")
YOUTUBE_CHANNEL_ID = _opt("YOUTUBE_CHANNEL_ID")

# Directorio de estado persistente (timers, tokens, etc.)
STATE_DIR = str(_RAIZ / "state")
Path(STATE_DIR).mkdir(exist_ok=True)

_TZINFO = ZoneInfo(CUANTICO_TIMEZONE)


def now_local() -> datetime:
    return datetime.now(_TZINFO)
