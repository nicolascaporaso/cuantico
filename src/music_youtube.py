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
from runtime_debug import dump_threads, heartbeat, mark_operation_end, mark_operation_start


_DEBUG_ENV_PATH = Path(__file__).resolve().parent.parent / ".dbg" / "unexpected-process-exit.env"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"
_LOCAL_MPV_STDERR_PATH = Path(config.STATE_DIR) / "mpv-local.log"
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


def _leer_log_local_mpv(max_chars: int = 1200) -> str:
    try:
        if not _LOCAL_MPV_STDERR_PATH.exists():
            return ""
        data = _LOCAL_MPV_STDERR_PATH.read_text(encoding="utf-8", errors="replace")
        return data[-max_chars:].strip()
    except Exception:
        return ""


def _limpiar_url(url: str) -> str:
    return (url or "").strip().strip("`").strip()


def _buscar_videos(query: str, limit: int) -> list[dict]:
    query = (query or "").strip()
    if not query:
        raise ValueError("faltó la búsqueda de música")

    if query.startswith(("http://", "https://")):
        return [{"title": query, "webpage_url": query}]

    limit = max(1, int(limit))
    fetch_limit = max(limit * 5, 8)
    target = f"ytsearch{fetch_limit}:{query}"
    data = json.loads(_run_yt_dlp(["--dump-single-json", "--flat-playlist", "--no-warnings", target]))
    entries = data.get("entries") or []
    resultados = []
    for entry in entries:
        if not entry:
            continue
        url = _limpiar_url(entry.get("url") or entry.get("webpage_url") or "")
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
            "title": (entry.get("title") or url).strip(),
            "webpage_url": url,
        })
        if len(resultados) >= limit:
            break
    return resultados


def _resolver_audio_url(video_url: str) -> str:
    salida = _run_yt_dlp(["--no-playlist", "-f", "bestaudio/best", "-g", video_url])
    url = next((_limpiar_url(line) for line in salida.splitlines() if line.strip()), "")
    if not url:
        raise RuntimeError("yt-dlp no devolvió una URL de audio reproducible")
    return url


def _preparar_item_rapido(result: dict) -> dict:
    webpage_url = _limpiar_url(result.get("webpage_url") or "")
    if not webpage_url:
        raise RuntimeError("faltó la URL del video de YouTube")
    return {
        "title": (result.get("title") or webpage_url).strip(),
        "webpage_url": webpage_url,
        "stream_url": _resolver_audio_url(webpage_url),
    }


def _esperar_socket_mpv(timeout_seg: float = 8.0, poll_seg: float = 0.05) -> bool:
    wait_token = mark_operation_start(
        "mpv-socket-wait",
        {"timeout_sec": timeout_seg, "socket_path": _socket_path},
    )
    heartbeat("mpv", {"state": "socket-wait-start", "timeout_sec": timeout_seg})
    _debug_emit("mpv-socket-wait-start", {"timeout_sec": timeout_seg, "socket_path": _socket_path})
    inicio = time.time()
    ready = False
    try:
        while time.time() - inicio < timeout_seg:
            if _mpv_process and _mpv_process.poll() is not None:
                _debug_emit("mpv-socket-wait-process-exited", {"returncode": _mpv_process.returncode})
                return False
            if _socket_path and os.path.exists(_socket_path):
                ready = True
                return True
            time.sleep(poll_seg)
        return False
    finally:
        elapsed = round(time.time() - inicio, 3)
        ended = mark_operation_end(wait_token, {"ready": ready, "elapsed_sec": elapsed})
        if ended:
            _debug_emit("mpv-socket-wait-end", ended)
        else:
            _debug_emit("mpv-socket-wait-end", {"ready": ready, "elapsed_sec": elapsed})
        heartbeat("mpv", {"state": "socket-wait-end", "ready": ready, "elapsed_sec": elapsed})
        if not ready and elapsed >= timeout_seg:
            dump_threads(
                "mpv-socket-wait-timeout",
                {"timeout_sec": timeout_seg, "socket_path": _socket_path},
            )


def _asegurar_socket(timeout_seg: float = 8.0) -> bool:
    return _esperar_socket_mpv(timeout_seg=timeout_seg)


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
    activar_local_despues = salida.get("kind") == "alsa_local" and salida.get("needs_gpio")
    stderr_target = subprocess.DEVNULL
    stderr_handle = None
    if activar_local_despues:
        try:
            _LOCAL_MPV_STDERR_PATH.parent.mkdir(parents=True, exist_ok=True)
            stderr_handle = open(_LOCAL_MPV_STDERR_PATH, "w", encoding="utf-8", errors="replace")
            stderr_target = stderr_handle
        except Exception as e:
            _debug_emit("mpv-local-log-open-failed", {"error": str(e), "path": str(_LOCAL_MPV_STDERR_PATH)})

    cmd = [
        config.MPV_COMMAND,
        "--no-terminal",
        "--really-quiet",
        "--video=no",
        "--audio-display=no",
        "--force-window=no",
        "--cache=yes",
        "--cache-secs=15",
        "--ao=alsa",
        f"--audio-device=alsa/{salida['device']}",
        f"--input-ipc-server={_socket_path}",
        "--network-timeout=10",
        *[item["stream_url"] for item in items],
    ]
    _debug_emit(
        "mpv-launching",
        {
            "device": salida["device"],
            "route_kind": salida["kind"],
            "route_label": salida["label"],
            "playlist_count": len(items),
            "local_stderr_log": str(_LOCAL_MPV_STDERR_PATH) if activar_local_despues else "",
        },
    )
    heartbeat("mpv", {"state": "launching", "playlist_count": len(items), "route_kind": salida["kind"]})
    try:
        _mpv_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
        )
        _debug_emit(
            "mpv-popen-returned",
            {
                "pid": _mpv_process.pid,
                "device": salida["device"],
                "route_kind": salida["kind"],
            },
        )
        _mpv_route = salida
        socket_ready = _asegurar_socket(timeout_seg=12.0 if activar_local_despues else 8.0)
        if not socket_ready:
            stderr_preview = _leer_log_local_mpv()
            if not _mpv_alive():
                _debug_emit(
                    "mpv-socket-timeout",
                    {
                        "device": salida["device"],
                        "route_kind": salida["kind"],
                        "error": "mpv terminó antes de abrir IPC",
                        "stderr_preview": stderr_preview,
                    },
                )
                raise RuntimeError(
                    "mpv terminó antes de abrir su socket IPC"
                    + (f" | stderr local: {stderr_preview[:300]}" if stderr_preview else "")
                )
            _debug_emit(
                "mpv-ipc-delayed",
                {
                    "device": salida["device"],
                    "route_kind": salida["kind"],
                    "stderr_preview": stderr_preview,
                },
            )
        if activar_local_despues:
            altavoz.activar_salida_audio(salida)
            _debug_emit(
                "local-audio-activated-after-mpv-ready" if socket_ready else "local-audio-activated-with-delayed-ipc",
                {"device": salida["device"], "label": salida["label"]},
            )
        else:
            altavoz.activar_salida_audio(salida)
        threading.Thread(target=_watch_process, args=(_mpv_process,), name="mpv-process-watch", daemon=True).start()
        _debug_emit(
            "mpv-started",
            {
                "pid": _mpv_process.pid,
                "device": salida["device"],
                "route_kind": salida["kind"],
                "route_label": salida["label"],
                "playlist_count": len(items),
                "direct_start": True,
                "ipc_ready": socket_ready,
            },
        )
        heartbeat("mpv", {"state": "started", "ipc_ready": socket_ready, "playlist_count": len(items)})
    except Exception:
        heartbeat("mpv", {"state": "start-error"})
        _cleanup_route()
        _mpv_process = None
        raise
    finally:
        if stderr_handle:
            try:
                stderr_handle.close()
            except Exception:
                pass


def _ipc_command(command: list, *, retries: int = 8, retry_delay_seg: float = 0.12):
    _maybe_cleanup_dead_process()
    if not _mpv_alive():
        raise RuntimeError("mpv no está corriendo")

    heartbeat("mpv", {"state": "ipc-command", "command": command})
    payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
    last_error = None
    for intento in range(retries):
        try:
            if not _esperar_socket_mpv(timeout_seg=2.5, poll_seg=0.05):
                raise RuntimeError("socket IPC de mpv todavía no existe")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(3)
                sock.connect(_socket_path)
                sock.sendall(payload)
                data = sock.recv(65536)
            break
        except (FileNotFoundError, ConnectionRefusedError, OSError, RuntimeError) as e:
            last_error = e
            _debug_emit(
                "mpv-ipc-retry",
                {
                    "command": command,
                    "attempt": intento + 1,
                    "retries": retries,
                    "error": str(e),
                },
            )
            _maybe_cleanup_dead_process()
            if not _mpv_alive():
                raise RuntimeError("mpv terminó antes de aceptar comandos IPC") from e
            if intento >= retries - 1:
                raise RuntimeError(f"mpv IPC no respondió tras {retries} intentos: {e}") from e
            time.sleep(retry_delay_seg)
    else:
        raise RuntimeError(f"mpv IPC no respondió: {last_error}")

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
            "direct_start": True,
        },
    )
    return True


def preparar_reproduccion(query: str) -> dict:
    resultados = _buscar_videos(query, 1)
    if not resultados:
        return {"ok": False, "error": f"No encontré nada en YouTube para '{query}'"}
    try:
        item = _preparar_item_rapido(resultados[0])
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _debug_emit("prepared-track", {"title": item["title"], "direct_start": True})
    return {"ok": True, "prepared": {"items": [item]}, "commentary": "", "title": item["title"]}


def preparar_playlist(query: str) -> dict:
    resultados = _buscar_videos(query, config.YOUTUBE_PLAYLIST_SEARCH_LIMIT)
    if not resultados:
        return {"ok": False, "error": f"No encontré resultados en YouTube para '{query}'"}
    playlist = []
    for result in resultados:
        try:
            item = _preparar_item_rapido(result)
        except Exception as e:
            _debug_emit("prepare-playlist-item-failed", {"title": result.get("title"), "error": str(e)})
            continue
        playlist.append(item)
        if len(playlist) >= config.YOUTUBE_AUDIO_SEARCH_LIMIT:
            break
    if not playlist:
        return {"ok": False, "error": f"No pude extraer audio reproducible para '{query}'"}
    return {"ok": True, "prepared": {"items": playlist}, "commentary": "", "title": playlist[0]["title"]}


def ejecutar_preparado(prepared: dict) -> bool:
    items = list(prepared.get("items") or [])
    return _cargar_playlist(items)


def reproducir(query: str | None = None) -> bool:
    if not query:
        return reanudar()
    info = preparar_reproduccion(query)
    if not info.get("ok"):
        print(f"   ⚠️ {info.get('error', 'No pude preparar la reproducción')}")
        return False
    print(f"   ▶️ YouTube: {info['title']}")
    return ejecutar_preparado(info["prepared"])


def reproducir_playlist(query: str) -> bool:
    info = preparar_playlist(query)
    if not info.get("ok"):
        print(f"   ⚠️ {info.get('error', 'No pude preparar la playlist')}")
        return False
    playlist = info["prepared"]["items"]
    print(f"   ▶️ YouTube playlist: {playlist[0]['title']} (+{len(playlist) - 1} más)")
    return ejecutar_preparado(info["prepared"])


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
