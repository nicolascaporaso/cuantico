import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import altavoz
import config


_DEBUG_ENV_PATH = Path(__file__).resolve().parent.parent / ".dbg" / "unexpected-process-exit.env"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"
_mpv_process = None
_mpv_route = None
_socket_path = config.MPV_IPC_SOCKET_PATH


def _debug_emit(msg: str, data: dict | None = None):
    payload = {
        "sessionId": "unexpected-process-exit",
        "runId": "pre-fix",
        "hypothesisId": "YT",
        "location": "music_youtube.py",
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
        req = urllib.request.Request(
            debug_url,
            data=line.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=0.8).read()
    except Exception:
        pass


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def disponible_para_reproducir() -> tuple[bool, str]:
    if not _command_exists(config.YT_DLP_COMMAND):
        return False, f"no encuentro {config.YT_DLP_COMMAND}; instala yt-dlp"
    if not _command_exists(config.MPV_COMMAND):
        return False, f"no encuentro {config.MPV_COMMAND}; instala mpv"
    return True, "ok"


def resumen_estado() -> dict:
    return {
        "yt_dlp_available": _command_exists(config.YT_DLP_COMMAND),
        "mpv_available": _command_exists(config.MPV_COMMAND),
        "mpv_running": _mpv_alive(),
        "socket_path": _socket_path,
    }


def inicializar():
    if _socket_path and os.path.exists(_socket_path):
        try:
            os.unlink(_socket_path)
        except OSError:
            pass


def _mpv_alive() -> bool:
    return _mpv_process is not None and _mpv_process.poll() is None


def _cleanup_route():
    global _mpv_route
    if _mpv_route:
        altavoz.desactivar_salida_audio(_mpv_route)
    _mpv_route = None


def _maybe_cleanup_dead_process():
    global _mpv_process
    if _mpv_process and _mpv_process.poll() is not None:
        _debug_emit("mpv-process-ended", {"returncode": _mpv_process.returncode})
        _mpv_process = None
        _cleanup_route()
        if _socket_path and os.path.exists(_socket_path):
            try:
                os.unlink(_socket_path)
            except OSError:
                pass


def _watch_process(proc: subprocess.Popen):
    proc.wait()
    global _mpv_process
    if _mpv_process is proc:
        _debug_emit("mpv-process-watch-end", {"returncode": proc.returncode})
        _mpv_process = None
        _cleanup_route()
        if _socket_path and os.path.exists(_socket_path):
            try:
                os.unlink(_socket_path)
            except OSError:
                pass


def _run_yt_dlp(args: list[str]) -> str:
    try:
        proc = subprocess.run(
            [config.YT_DLP_COMMAND, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=45,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"yt-dlp no está instalado ({config.YT_DLP_COMMAND})") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("yt-dlp tardó demasiado en responder") from e

    salida = (proc.stdout or "").strip()
    error = (proc.stderr or "").strip()
    _debug_emit(
        "yt-dlp-run",
        {
            "args": args,
            "returncode": proc.returncode,
            "stdout_preview": salida[:200],
            "stderr_preview": error[:200],
        },
    )
    if proc.returncode != 0:
        raise RuntimeError(error or salida or "yt-dlp devolvió error")
    return salida


def _buscar_videos(query: str, limit: int) -> list[dict]:
    query = (query or "").strip()
    if not query:
        raise ValueError("faltó la búsqueda de música")

    if query.startswith(("http://", "https://")):
        data = json.loads(
            _run_yt_dlp(["--dump-single-json", "--no-warnings", "--no-playlist", query])
        )
        return [{
            "title": data.get("title") or query,
            "webpage_url": data.get("webpage_url") or query,
        }]

    limit = max(1, int(limit))
    # yt-dlp/YouTube a veces devuelve canales o playlists como primer resultado.
    # Pedimos más resultados y filtramos manualmente solo videos reproducibles.
    fetch_limit = max(limit * 5, 8)
    target = f"ytsearch{fetch_limit}:{query}"
    data = json.loads(
        _run_yt_dlp(["--dump-single-json", "--flat-playlist", "--no-warnings", target])
    )
    entries = data.get("entries") or []
    resultados = []
    for entry in entries:
        if not entry:
            continue
        url = (entry.get("url") or entry.get("webpage_url") or "").strip()
        if url and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        if not url:
            continue

        lower_url = url.lower()
        es_video = "watch?v=" in lower_url or "youtu.be/" in lower_url
        if not es_video:
            _debug_emit(
                "yt-search-skip-non-video",
                {
                    "title": entry.get("title") or url,
                    "url": url,
                    "entry_type": entry.get("_type"),
                },
            )
            continue

        resultados.append({
            "title": entry.get("title") or url,
            "webpage_url": url,
        })
        if len(resultados) >= limit:
            break
    return resultados


def _resolver_audio_url(video_url: str) -> str:
    salida = _run_yt_dlp(["--no-playlist", "-f", "bestaudio", "-g", video_url])
    url = next((line.strip() for line in salida.splitlines() if line.strip()), "")
    if not url:
        raise RuntimeError("yt-dlp no devolvió una URL de audio reproducible")
    return url


def _asegurar_socket():
    for _ in range(30):
        if _socket_path and os.path.exists(_socket_path):
            return
        time.sleep(0.1)
    raise RuntimeError("mpv no abrió su socket IPC a tiempo")


def _iniciar_mpv(items: list[dict]):
    global _mpv_process, _mpv_route
    _maybe_cleanup_dead_process()
    if _mpv_alive():
        detener()

    ok, motivo = disponible_para_reproducir()
    if not ok:
        raise RuntimeError(motivo)

    if _socket_path and os.path.exists(_socket_path):
        try:
            os.unlink(_socket_path)
        except OSError:
            pass

    salida = altavoz.resolver_salida_audio()
    altavoz.activar_salida_audio(salida)
    cmd = [
        config.MPV_COMMAND,
        "--really-quiet",
        "--video=no",
        "--audio-display=no",
        "--force-window=no",
        "--ao=alsa",
        f"--audio-device=alsa/{salida['device']}",
        f"--input-ipc-server={_socket_path}",
        *[item["stream_url"] for item in items],
    ]
    try:
        _mpv_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _mpv_route = salida
        _asegurar_socket()
        threading.Thread(target=_watch_process, args=(_mpv_process,), daemon=True).start()
        _debug_emit(
            "mpv-started",
            {
                "pid": _mpv_process.pid,
                "device": salida["device"],
                "route_kind": salida["kind"],
                "route_label": salida["label"],
                "playlist_count": len(items),
            },
        )
    except Exception:
        _cleanup_route()
        _mpv_process = None
        raise


def _ipc_command(command: list):
    _maybe_cleanup_dead_process()
    if not _mpv_alive():
        raise RuntimeError("mpv no está corriendo")

    payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3)
        sock.connect(_socket_path)
        sock.sendall(payload)
        data = sock.recv(65536)
    response = json.loads(data.decode("utf-8", errors="replace") or "{}")
    if response.get("error") not in (None, "success"):
        raise RuntimeError(f"mpv IPC error: {response.get('error')}")
    _debug_emit("mpv-ipc", {"command": command, "response": response})
    return response.get("data")


def _cargar_playlist(items: list[dict]) -> bool:
    if not items:
        return False
    _iniciar_mpv(items)
    _debug_emit(
        "playlist-loaded",
        {
            "count": len(items),
            "first_title": items[0]["title"],
        },
    )
    return True


def reproducir(query: str | None = None) -> bool:
    if not query:
        return reanudar()
    resultados = _buscar_videos(query, 1)
    if not resultados:
        print(f"   ⚠️ No encontré nada en YouTube para '{query}'")
        return False
    item = resultados[0]
    item["stream_url"] = _resolver_audio_url(item["webpage_url"])
    print(f"   ▶️ YouTube: {item['title']}")
    return _cargar_playlist([item])


def reproducir_playlist(query: str) -> bool:
    resultados = _buscar_videos(query, config.YOUTUBE_PLAYLIST_SEARCH_LIMIT)
    if not resultados:
        print(f"   ⚠️ No encontré resultados en YouTube para '{query}'")
        return False
    playlist = []
    for item in resultados:
        try:
            item["stream_url"] = _resolver_audio_url(item["webpage_url"])
        except Exception as e:
            _debug_emit("resolve-audio-url-failed", {"title": item["title"], "error": str(e)})
            continue
        playlist.append(item)
        if len(playlist) >= config.YOUTUBE_AUDIO_SEARCH_LIMIT:
            break
    if not playlist:
        print(f"   ⚠️ No pude extraer audio reproducible para '{query}'")
        return False
    print(f"   ▶️ YouTube playlist: {playlist[0]['title']} (+{len(playlist) - 1} más)")
    return _cargar_playlist(playlist)


def reanudar() -> bool:
    _maybe_cleanup_dead_process()
    if not _mpv_alive():
        return False
    _ipc_command(["set_property", "pause", False])
    return True


def pausar() -> bool:
    _maybe_cleanup_dead_process()
    if not _mpv_alive():
        return False
    _ipc_command(["set_property", "pause", True])
    return True


def siguiente() -> bool:
    _maybe_cleanup_dead_process()
    if not _mpv_alive():
        return False
    _ipc_command(["playlist-next", "force"])
    return True


def anterior() -> bool:
    _maybe_cleanup_dead_process()
    if not _mpv_alive():
        return False
    _ipc_command(["playlist-prev", "force"])
    return True


def volumen(delta: int) -> bool:
    _maybe_cleanup_dead_process()
    if not _mpv_alive():
        return False
    actual = _ipc_command(["get_property", "volume"])
    if actual is None:
        actual = 50
    nuevo = int(max(0, min(100, int(actual) + int(delta))))
    _ipc_command(["set_property", "volume", nuevo])
    print(f"   🔉 Volumen YouTube/mpv: {int(actual)}% → {nuevo}%")
    return True


def detener() -> bool:
    global _mpv_process
    _maybe_cleanup_dead_process()
    if not _mpv_alive():
        return False
    try:
        _ipc_command(["quit"])
    except Exception:
        try:
            _mpv_process.terminate()
        except Exception:
            pass
    _mpv_process = None
    _cleanup_route()
    if _socket_path and os.path.exists(_socket_path):
        try:
            os.unlink(_socket_path)
        except OSError:
            pass
    return True
