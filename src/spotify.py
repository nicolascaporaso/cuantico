import time
import traceback
import requests
import spotipy
import urllib3
from spotipy.oauth2 import SpotifyOAuth
import config

SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

# Trozos del nombre del dispositivo Raspotify en Spotify (primero que case gana).
# Raspotify por defecto publica como "raspotify", pero a veces toma el hostname (ej: "Cuantico").
DEVICE_HINTS = ["raspotify", "cuantico"]

_sp = None
_device_id = None
_last_error = ""
_spotify_available = False
_spotify_init_attempted = False


def _log(msg: str):
    print(f"[Spotify] {msg}")


def _deshabilitar(reason: str, exc: Exception | None = None):
    global _sp, _device_id, _last_error, _spotify_available
    _sp = None
    _device_id = None
    _spotify_available = False
    _last_error = reason
    _log(f"Error durante la inicialización: {reason}")
    if exc is not None:
        detalle = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if detalle.strip():
            print(detalle, end="" if detalle.endswith("\n") else "\n")
    _log("Spotify deshabilitado. El asistente continuará sin este servicio.")


def inicializar(origen: str = "startup") -> bool:
    global _sp, _last_error, _spotify_available, _spotify_init_attempted
    _spotify_init_attempted = True
    _log("Inicializando...")
    # Spotify opcional
    if not config.SPOTIFY_ENABLED:
        _log("Spotify deshabilitado en configuración.")
        _sp = None
        _spotify_available = False
        _last_error = "Spotify está deshabilitado en .env"
        return False

    try:
        auth = SpotifyOAuth(
            client_id=config.SPOTIFY_CLIENT_ID,
            client_secret=config.SPOTIFY_CLIENT_SECRET,
            redirect_uri=config.SPOTIFY_REDIRECT_URI,
            scope=SCOPES,
            open_browser=False,
            cache_path=".spotify_cache",
        )
        _sp = spotipy.Spotify(
            auth_manager=auth,
            requests_timeout=5,
            retries=0,
            status_retries=0,
            backoff_factor=0,
        )
        _sp.current_user()  # fuerza la validación del token
        _spotify_available = True
        _last_error = ""
        _log("Inicializado correctamente.")
        print("ðŸŽµ Dispositivos Spotify visibles:")
        if origen == "startup":
            _refrescar_dispositivo(verboso=True, reintentos=1, espera=0)
        else:
            _refrescar_dispositivo(verboso=True, reintentos=2, espera=2)
        if _device_id:
            _log(f"Cuántico usará: {_device_id[:8]}…")
        else:
            _log(f"Ningún dispositivo coincide con {DEVICE_HINTS}. Spotify quedó inicializado pero sin device visible.")
        return True
    except spotipy.exceptions.SpotifyException as e:
        if getattr(e, "http_status", None) == 429:
            _deshabilitar("Rate limit (HTTP 429) durante la inicialización", e)
        else:
            _deshabilitar(f"SpotifyException durante la inicialización: {e}", e)
    except (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.RequestException,
        urllib3.exceptions.HTTPError,
        urllib3.exceptions.MaxRetryError,
        urllib3.exceptions.NewConnectionError,
        TimeoutError,
    ) as e:
        _deshabilitar("error de red durante la inicialización", e)
    except Exception as e:
        _deshabilitar("fallo inesperado durante la inicialización", e)
    return False


def asegurar_inicializado() -> bool:
    if _spotify_available and _sp:
        return True
    return inicializar(origen="on-demand")


def disponible_para_backend() -> tuple[bool, str]:
    if not config.SPOTIFY_ENABLED:
        return False, "Spotify está deshabilitado en .env"
    if not _spotify_available or _sp is None:
        detalle = _last_error or "Spotify no inicializa correctamente"
        return False, f"Spotify no inicializa correctamente: {detalle}"
    return True, "ok"


def _refrescar_dispositivo(verboso=False, reintentos=1, espera=3):
    """Busca el dispositivo Raspotify. Si no lo encuentra, reintenta con espera (para dar tiempo a que se registre tras boot)."""
    global _device_id
    _device_id = None
    if not _sp:
        return
    for intento in range(reintentos):
        try:
            devices = _sp.devices().get("devices", [])
            if verboso:
                if not devices:
                    print("   (Spotify no ve ningún dispositivo — ¿Raspotify arrancado en la Pi?)")
                for d in devices:
                    print(f"   · '{d['name']}' | tipo={d.get('type')} | activo={d.get('is_active')} | id={d['id'][:8]}…")
            for hint in DEVICE_HINTS:
                for d in devices:
                    if hint.lower() in d["name"].lower():
                        _device_id = d["id"]
                        return
            # No encontrado: esperamos y reintentamos si quedan intentos
            if intento < reintentos - 1:
                if verboso:
                    print(f"   ⏳ Raspotify no visible todavía, reintentando en {espera}s…")
                time.sleep(espera)
        except Exception as e:
            print(f"⚠️ Spotify error listando dispositivos: {e}")
            return


def _estado_playback():
    if not _sp:
        return None
    try:
        return _sp.current_playback()
    except Exception as e:
        _log(f"error leyendo playback actual: {e}")
        return None


def _resolver_kwargs_device_id() -> dict:
    global _device_id
    if _device_id:
        return {"device_id": _device_id}
    estado = _estado_playback()
    activo = (estado or {}).get("device", {}) if isinstance(estado, dict) else {}
    activo_id = activo.get("id")
    if activo_id:
        _device_id = activo_id
        print(f"   🎵 Usando dispositivo activo de Spotify: {_device_id[:8]}…")
        return {"device_id": _device_id}
    return {}


def disponible_para_reproducir() -> tuple[bool, str]:
    if not asegurar_inicializado():
        detalle = _last_error or "Spotify no inicializa correctamente"
        return False, f"Spotify no disponible: {detalle}"
    _refrescar_dispositivo()
    return True, "ok"


def resumen_estado() -> dict:
    return {
        "enabled": config.SPOTIFY_ENABLED,
        "initialized": _sp is not None,
        "available": _spotify_available,
        "init_attempted": _spotify_init_attempted,
        "device_id": _device_id,
        "device_hints": DEVICE_HINTS[:],
        "last_error": _last_error,
    }


def estado_reproduccion() -> dict:
    if not _spotify_available or not _sp:
        return {
            "backend": "spotify",
            "active": False,
            "paused": False,
            "reason": "spotify-unavailable",
            "error": _last_error,
        }
    estado = _estado_playback()
    if not isinstance(estado, dict):
        return {
            "backend": "spotify",
            "active": False,
            "paused": False,
            "reason": "no-playback",
        }
    activo = bool(estado.get("is_playing"))
    dispositivo = estado.get("device") or {}
    return {
        "backend": "spotify",
        "active": activo,
        "paused": not activo,
        "reason": "playing" if activo else "paused-or-idle",
        "device_name": dispositivo.get("name"),
        "device_is_active": dispositivo.get("is_active"),
    }


def hay_reproduccion_activa() -> bool:
    return bool(estado_reproduccion().get("active"))


def reanudar() -> bool:
    ok, motivo = disponible_para_reproducir()
    if not ok:
        _log(motivo)
        return False
    try:
        _sp.start_playback(**_resolver_kwargs_device_id())
        return True
    except Exception as e:
        _log(f"error reanudar: {e}")
        return False


def detener() -> bool:
    # Spotify no tiene "stop" real vía Web API; usar pausa evita que siga sonando.
    return pausar()


def pausar_para_conversacion() -> bool:
    return pausar()


def reproducir(query=None):
    ok, motivo = disponible_para_reproducir()
    if not ok:
        _log(motivo)
        return False
    _refrescar_dispositivo(verboso=True)
    kwargs_device = _resolver_kwargs_device_id()
    try:
        if query:
            r = _sp.search(q=query, type="track", limit=1)
            items = r.get("tracks", {}).get("items", [])
            if not items:
                print(f"   ⚠️ Sin resultados para '{query}'")
                return False
            _sp.start_playback(uris=[items[0]["uri"]], **kwargs_device)
            print(f"   🎵 Reproduciendo: {items[0].get('name', '?')}")
        else:
            # Sin query → solo tiene sentido "reanudar" si había algo sonando antes Y el device actual es ese.
            estado = _estado_playback()
            hay_que_reanudar = bool(
                estado
                and estado.get("item")
                and (
                    not _device_id
                    or estado.get("device", {}).get("id") == _device_id
                )
            )
            if hay_que_reanudar:
                _sp.start_playback(**kwargs_device)
                print("   🎵 Reanudando reproducción previa.")
            else:
                print("   🎵 Sin contexto previo en Raspotify; lanzo tracks genéricos.")
                r = _sp.search(q="top hits", type="track", limit=5)
                items = r.get("tracks", {}).get("items", [])
                if not items:
                    print("   ⚠️ Búsqueda genérica vacía.")
                    return False
                _sp.start_playback(uris=[t["uri"] for t in items], **kwargs_device)
                print(f"   🎵 {len(items)} tracks genéricos cargados.")
        return True
    except Exception as e:
        _log(f"error play: {e}")
        return False


def reproducir_playlist(query):
    """Busca tracks que casen con `query` (género/ambiente) y los reproduce como cola."""
    ok, motivo = disponible_para_reproducir()
    if not ok:
        _log(motivo)
        return False
    _refrescar_dispositivo()
    kwargs_device = _resolver_kwargs_device_id()
    try:
        # Buscamos tracks directamente (no playlists) — esquiva el bug de
        # "context is not available" con playlists editoriales Default de Spotify.
        # Spotify restringe /search en apps "development mode" — usamos limit bajo.
        track_uris: list[str] = []
        for intento_limit in (5, 3, 1):
            try:
                r = _sp.search(q=query, type="track", limit=intento_limit)
                tracks = r.get("tracks", {}).get("items", [])
                track_uris = [t["uri"] for t in tracks if t and t.get("uri")]
                if track_uris:
                    break
            except Exception as inner:
                print(f"   ⚠️ search limit={intento_limit} falló: {inner}")
                continue
        if not track_uris:
            print(f"   ⚠️ Ningún track encontrado para '{query}'")
            return False
        _sp.start_playback(uris=track_uris, **kwargs_device)
        try:
            _sp.shuffle(True, **kwargs_device)
        except Exception:
            pass  # shuffle falla a veces justo tras start_playback; no es crítico
        print(f"   🎧 {len(track_uris)} tracks cargados para '{query}'")
        return True
    except Exception as e:
        _log(f"error playlist: {e}")
        return False


def pausar():
    ok, _ = disponible_para_reproducir()
    if not ok:
        _log("Spotify no disponible.")
        return False
    try:
        _sp.pause_playback(**_resolver_kwargs_device_id())
        return True
    except Exception as e:
        _log(f"error pausa: {e}")
        return False


def siguiente():
    ok, _ = disponible_para_reproducir()
    if not ok:
        _log("Spotify no disponible.")
        return False
    try:
        _sp.next_track(**_resolver_kwargs_device_id())
        return True
    except Exception as e:
        _log(f"error siguiente: {e}")
        return False


def anterior():
    ok, _ = disponible_para_reproducir()
    if not ok:
        _log("Spotify no disponible.")
        return False
    try:
        _sp.previous_track(**_resolver_kwargs_device_id())
        return True
    except Exception as e:
        _log(f"error anterior: {e}")
        return False


def volumen(delta):
    """delta: entero positivo para subir, negativo para bajar."""
    ok, _ = disponible_para_reproducir()
    if not ok:
        _log("Spotify no disponible.")
        return False
    try:
        estado = _estado_playback()
        if not estado:
            return False
        actual = int(estado.get("device", {}).get("volume_percent", 50) or 50)
        nuevo = int(max(0, min(100, actual + int(delta))))
        _sp.volume(nuevo, **_resolver_kwargs_device_id())
        print(f"   🔉 Volumen Spotify: {actual}% → {nuevo}%")
        return True
    except Exception as e:
        _log(f"error volumen: {e}")
        return False
