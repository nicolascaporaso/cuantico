import json
from pathlib import Path

import config
import music_youtube
import spotify


_STATE_PATH = Path(config.STATE_DIR) / "music_backend.json"
_VALID_BACKENDS = {"spotify", "youtube"}


def _sanitize_backend(value: str | None) -> str:
    backend = (value or "").strip().lower()
    if backend in _VALID_BACKENDS:
        return backend
    default_backend = (config.MUSIC_BACKEND_DEFAULT or "spotify").strip().lower()
    return default_backend if default_backend in _VALID_BACKENDS else "spotify"


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        backend = _sanitize_backend(None)
        return {"backend": backend, "last_backend": backend}
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            backend = _sanitize_backend(data.get("backend"))
            last_backend = _sanitize_backend(data.get("last_backend") or backend)
            return {"backend": backend, "last_backend": last_backend}
    except Exception:
        pass
    backend = _sanitize_backend(None)
    return {"backend": backend, "last_backend": backend}


def _save_state(data: dict):
    backend = _sanitize_backend(data.get("backend"))
    last_backend = _sanitize_backend(data.get("last_backend") or backend)
    _STATE_PATH.write_text(
        json.dumps({"backend": backend, "last_backend": last_backend}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def inicializar():
    spotify.inicializar()
    music_youtube.inicializar()
    if not _STATE_PATH.exists():
        backend = _sanitize_backend(None)
        _save_state({"backend": backend, "last_backend": backend})


def backend_actual() -> str:
    return _load_state()["backend"]


def seleccionar_backend(backend: str) -> str:
    state = _load_state()
    backend = _sanitize_backend(backend)
    _save_state({"backend": backend, "last_backend": state.get("last_backend", backend)})
    return backend


def resumen_backend_actual() -> str:
    state = _load_state()
    actual = state["backend"]
    spotify_ok, spotify_msg = spotify.disponible_para_reproducir()
    youtube_ok, youtube_msg = music_youtube.disponible_para_reproducir()
    return (
        f"backend actual: {actual}. "
        f"ultimo backend con reproduccion: {state['last_backend']}. "
        f"Spotify: {'ok' if spotify_ok else spotify_msg}. "
        f"YouTube: {'ok' if youtube_ok else youtube_msg}."
    )


def _backend_module(backend: str | None = None):
    elegido = _sanitize_backend(backend or backend_actual())
    if elegido == "youtube":
        return elegido, music_youtube
    return elegido, spotify


def _backend_control() -> tuple[str, object]:
    state = _load_state()
    return _backend_module(state.get("last_backend") or state.get("backend"))


def disponible_para_reproducir(backend: str | None = None) -> tuple[bool, str]:
    elegido, modulo = _backend_module(backend)
    ok, motivo = modulo.disponible_para_reproducir()
    if ok:
        return True, f"{elegido} listo"
    return False, f"{elegido}: {motivo}"


def reproducir(query: str | None = None, backend: str | None = None) -> bool:
    elegido, modulo = _backend_module(backend)
    ok = modulo.reproducir(query)
    if ok:
        state = _load_state()
        _save_state({"backend": state["backend"], "last_backend": elegido})
    return ok


def reproducir_playlist(query: str, backend: str | None = None) -> bool:
    elegido, modulo = _backend_module(backend)
    ok = modulo.reproducir_playlist(query)
    if ok:
        state = _load_state()
        _save_state({"backend": state["backend"], "last_backend": elegido})
    return ok


def reanudar(backend: str | None = None) -> bool:
    elegido, modulo = _backend_module(backend or _load_state().get("last_backend"))
    ok = modulo.reanudar()
    if ok:
        state = _load_state()
        _save_state({"backend": state["backend"], "last_backend": elegido})
    return ok


def pausar(backend: str | None = None) -> bool:
    _, modulo = _backend_module(backend) if backend else _backend_control()
    return modulo.pausar()


def siguiente(backend: str | None = None) -> bool:
    _, modulo = _backend_module(backend) if backend else _backend_control()
    return modulo.siguiente()


def anterior(backend: str | None = None) -> bool:
    _, modulo = _backend_module(backend) if backend else _backend_control()
    return modulo.anterior()


def volumen(delta: int, backend: str | None = None) -> bool:
    _, modulo = _backend_module(backend) if backend else _backend_control()
    return modulo.volumen(delta)


def detener_todo() -> bool:
    return music_youtube.detener()
