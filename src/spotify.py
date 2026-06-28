import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import config

SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

# Trozos del nombre del dispositivo Raspotify en Spotify (primero que case gana).
# Raspotify por defecto publica como "raspotify", pero a veces toma el hostname (ej: "Cuantico").
DEVICE_HINTS = ["raspotify", "cuantico"]

_sp = None
_device_id = None


def inicializar():
    global _sp
    # Spotify opcional
    if not config.SPOTIFY_ENABLED:
        print("🎵 Spotify deshabilitado")
        _sp = None
        return

    try:
        auth = SpotifyOAuth(
            client_id=config.SPOTIFY_CLIENT_ID,
            client_secret=config.SPOTIFY_CLIENT_SECRET,
            redirect_uri=config.SPOTIFY_REDIRECT_URI,
            scope=SCOPES,
            open_browser=False,
            cache_path=".spotify_cache",
        )
        _sp = spotipy.Spotify(auth_manager=auth)
        _sp.current_user()  # fuerza la validación del token
        print("🎵 Dispositivos Spotify visibles:")
        # En el arranque damos varios intentos por si Raspotify aún está negociando.
        _refrescar_dispositivo(verboso=True, reintentos=4, espera=3)
        if _device_id:
            print(f"🎵 Cuántico usará: {_device_id[:8]}…")
        else:
            print(f"⚠️ Ningún dispositivo coincide con {DEVICE_HINTS}. Ajusta DEVICE_HINTS en spotify.py con el nombre real que veas arriba.")
    except Exception as e:
        print(f"⚠️ Spotify no disponible: {e}")
        _sp = None


def asegurar_inicializado() -> bool:
    if _sp:
        return True
    inicializar()
    return _sp is not None


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


def disponible_para_reproducir() -> tuple[bool, str]:
    if not config.SPOTIFY_ENABLED:
        return False, "Spotify está deshabilitado en .env"
    if not asegurar_inicializado():
        return False, "Spotify no inicializa correctamente"
    _refrescar_dispositivo()
    if not _device_id:
        return False, "no veo un dispositivo Spotify Connect llamado raspotify o cuantico"
    return True, "ok"


def resumen_estado() -> dict:
    return {
        "enabled": config.SPOTIFY_ENABLED,
        "initialized": _sp is not None,
        "device_id": _device_id,
        "device_hints": DEVICE_HINTS[:],
    }


def reproducir(query=None):
    ok, motivo = disponible_para_reproducir()
    if not ok:
        print(f"   ⚠️ {motivo}")
        return False
    _refrescar_dispositivo(verboso=True)
    try:
        if query:
            r = _sp.search(q=query, type="track", limit=1)
            items = r.get("tracks", {}).get("items", [])
            if not items:
                print(f"   ⚠️ Sin resultados para '{query}'")
                return False
            _sp.start_playback(device_id=_device_id, uris=[items[0]["uri"]])
            print(f"   🎵 Reproduciendo: {items[0].get('name', '?')}")
        else:
            # Sin query → solo tiene sentido "reanudar" si había algo sonando antes Y el device actual es ese.
            try:
                estado = _sp.current_playback()
            except Exception:
                estado = None
            hay_que_reanudar = bool(
                estado
                and estado.get("item")
                and estado.get("device", {}).get("id") == _device_id
            )
            if hay_que_reanudar:
                _sp.start_playback(device_id=_device_id)
                print("   🎵 Reanudando reproducción previa.")
            else:
                print("   🎵 Sin contexto previo en Raspotify; lanzo tracks genéricos.")
                r = _sp.search(q="top hits", type="track", limit=5)
                items = r.get("tracks", {}).get("items", [])
                if not items:
                    print("   ⚠️ Búsqueda genérica vacía.")
                    return False
                _sp.start_playback(device_id=_device_id, uris=[t["uri"] for t in items])
                print(f"   🎵 {len(items)} tracks genéricos cargados.")
        return True
    except Exception as e:
        print(f"⚠️ Spotify error play: {e}")
        return False


def reproducir_playlist(query):
    """Busca tracks que casen con `query` (género/ambiente) y los reproduce como cola."""
    ok, motivo = disponible_para_reproducir()
    if not ok:
        print(f"   ⚠️ {motivo}")
        return False
    _refrescar_dispositivo()
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
        _sp.start_playback(device_id=_device_id, uris=track_uris)
        try:
            _sp.shuffle(True, device_id=_device_id)
        except Exception:
            pass  # shuffle falla a veces justo tras start_playback; no es crítico
        print(f"   🎧 {len(track_uris)} tracks cargados para '{query}'")
        return True
    except Exception as e:
        print(f"⚠️ Spotify error playlist: {e}")
        return False


def pausar():
    ok, _ = disponible_para_reproducir()
    if not ok:
        return False
    try:
        _sp.pause_playback(device_id=_device_id)
        return True
    except Exception as e:
        print(f"⚠️ Spotify error pausa: {e}")
        return False


def siguiente():
    ok, _ = disponible_para_reproducir()
    if not ok:
        return False
    try:
        _sp.next_track(device_id=_device_id)
        return True
    except Exception as e:
        print(f"⚠️ Spotify error siguiente: {e}")
        return False


def anterior():
    ok, _ = disponible_para_reproducir()
    if not ok:
        return False
    try:
        _sp.previous_track(device_id=_device_id)
        return True
    except Exception as e:
        print(f"⚠️ Spotify error anterior: {e}")
        return False


def volumen(delta):
    """delta: entero positivo para subir, negativo para bajar."""
    ok, _ = disponible_para_reproducir()
    if not ok:
        return False
    try:
        estado = _sp.current_playback()
        if not estado:
            return False
        actual = int(estado.get("device", {}).get("volume_percent", 50) or 50)
        nuevo = int(max(0, min(100, actual + int(delta))))
        _sp.volume(nuevo, device_id=_device_id)
        print(f"   🔉 Volumen Spotify: {actual}% → {nuevo}%")
        return True
    except Exception as e:
        print(f"⚠️ Spotify error volumen: {e}")
        return False
