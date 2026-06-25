"""Integración con Google Calendar (OAuth Desktop).

El mismo Client ID se comparte con YouTube (ver youtube_stats.py): los scopes
se declaran aquí en SCOPES para que el primer flow los autorice todos.

- En el Mac (primer run): abre navegador local y guarda state/google_token.json.
- En la Pi: sólo refresca el token existente, no necesita navegador.
"""
import datetime as dt
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config

# OJO: cualquier cambio aquí invalida el token existente. Hay que borrar
# state/google_token.json y re-autorizar en el Mac.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

_servicio = None
_credenciales: Credentials | None = None


def obtener_credenciales() -> Credentials:
    """Flujo compartido con youtube_stats. Devuelve credenciales válidas o lanza."""
    global _credenciales
    if _credenciales and _credenciales.valid:
        return _credenciales

    token_path = Path(config.GOOGLE_TOKEN_PATH)
    client_path = Path(config.GOOGLE_CLIENT_SECRETS_PATH)

    creds: Credentials | None = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            print(f"⚠️ token.json inválido: {e}. Hay que re-autorizar.")

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"⚠️ Refresh falló: {e}. Hay que re-autorizar.")
            creds = None

    if not creds or not creds.valid:
        if not client_path.exists():
            raise RuntimeError(
                f"Falta {client_path}. Descárgalo de Google Cloud Console "
                f"(OAuth 2.0 Desktop) y cópialo ahí."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(exist_ok=True)
        token_path.write_text(creds.to_json())
        print(f"✅ Token guardado en {token_path}. Cópialo a la Pi con scp.")

    _credenciales = creds
    return creds


def inicializar() -> bool:
    global _servicio
    try:
        creds = obtener_credenciales()
        _servicio = build("calendar", "v3", credentials=creds, cache_discovery=False)
        print("📅 Google Calendar listo.")
        return True
    except Exception as e:
        print(f"⚠️ Calendar no disponible: {e}")
        _servicio = None
        return False


def _listar_eventos(inicio: dt.datetime, fin: dt.datetime) -> list[dict]:
    if not _servicio:
        return []
    ahora_iso = inicio.isoformat() + "Z" if inicio.tzinfo is None else inicio.isoformat()
    fin_iso = fin.isoformat() + "Z" if fin.tzinfo is None else fin.isoformat()
    r = _servicio.events().list(
        calendarId="primary",
        timeMin=ahora_iso,
        timeMax=fin_iso,
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()
    eventos = []
    for e in r.get("items", []):
        inicio_raw = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
        fin_raw = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", "")
        eventos.append({
            "titulo": e.get("summary", "(sin título)"),
            "inicio_iso": inicio_raw,
            "fin_iso": fin_raw,
            "ubicacion": e.get("location", ""),
        })
    return eventos


def eventos_hoy() -> list[dict]:
    ahora = dt.datetime.utcnow()
    medianoche = (ahora + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return _listar_eventos(ahora, medianoche)


def eventos_semana() -> list[dict]:
    ahora = dt.datetime.utcnow()
    return _listar_eventos(ahora, ahora + dt.timedelta(days=7))


def crear_evento(titulo: str, inicio_iso: str, duracion_min: int = 30, descripcion: str = "") -> dict:
    if not _servicio:
        raise RuntimeError("Calendar no inicializado")
    inicio_dt = dt.datetime.fromisoformat(inicio_iso.replace("Z", "+00:00"))
    fin_dt = inicio_dt + dt.timedelta(minutes=duracion_min)
    body = {
        "summary": titulo,
        "description": descripcion,
        "start": {"dateTime": inicio_dt.isoformat(), "timeZone": config.CUANTICO_TIMEZONE},
        "end": {"dateTime": fin_dt.isoformat(), "timeZone": config.CUANTICO_TIMEZONE},
    }
    e = _servicio.events().insert(calendarId="primary", body=body).execute()
    return {"id": e.get("id"), "html_link": e.get("htmlLink")}
