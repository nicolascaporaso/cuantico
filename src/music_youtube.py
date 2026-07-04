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


# ---------------- DEBUG ----------------

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
            for l in _DEBUG_ENV_PATH.read_text(encoding="utf-8").splitlines():
                if l.startswith("DEBUG_SERVER_URL="):
                    debug_url = l.split("=", 1)[1].strip()

        req = urllib.request.Request(
            debug_url,
            data=line.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=0.5).read()
    except Exception:
        pass


# ---------------- UTILS ----------------

def _command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def disponible_para_reproducir():
    if not _command_exists(config.YT_DLP_COMMAND):
        return False, "falta yt-dlp"
    if not _command_exists(config.MPV_COMMAND):
        return False, "falta mpv"
    return True, "ok"


def _mpv_alive():
    return _mpv_process is not None and _mpv_process.poll() is None


def inicializar():
    if _socket_path and os.path.exists(_socket_path):
        try:
            os.unlink(_socket_path)
        except OSError:
            pass


# ---------------- YT-DLP OPTIMIZADO (FIX CLAVE) ----------------

def _run_yt_dlp(args, timeout_s=30):
    proc = subprocess.run(
        [config.YT_DLP_COMMAND, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        check=False,
    )

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "yt-dlp error")

    return proc.stdout.strip()


def _buscar_videos(query: str, limit: int):
    if query.startswith("http"):
        return [{"title": query, "webpage_url": query}]

    raw = _run_yt_dlp([
        "--dump-json",
        "--flat-playlist",
        f"ytsearch{limit}:{query}"
    ], timeout_s=20)

    results = []
    for line in raw.splitlines():
        try:
            data = json.loads(line)
            vid = data.get("url") or data.get("id")
            if not vid:
                continue

            if not vid.startswith("http"):
                vid = f"https://www.youtube.com/watch?v={vid}"

            results.append({
                "title": data.get("title") or vid,
                "webpage_url": vid
            })
        except Exception:
            continue

    return results


# ---------------- AUDIO RESOLVER (FIX IMPORTANTE) ----------------

def _resolver_audio(video_url: str):
    """
    FIX PRINCIPAL:
    dejamos de inspeccionar formatos uno por uno.
    yt-dlp ya sabe elegir mejor audio.
    """
    try:
        url = _run_yt_dlp([
            "-f", "bestaudio/best",
            "-g",
            video_url
        ], timeout_s=20)

        return url.strip() if url else None
    except Exception as e:
        _debug_emit("audio-resolve-failed", {"error": str(e)})
        return None


def _preparar_item(result):
    url = _resolver_audio(result["webpage_url"])
    if not url:
        return None

    return {
        "title": result["title"],
        "webpage_url": result["webpage_url"],
        "stream_url": url
    }


# ---------------- MPV ----------------

def _iniciar_mpv(items):
    global _mpv_process, _mpv_route

    if _mpv_alive():
        detener()

    salida = altavoz.resolver_salida_audio()

    cmd = [
        config.MPV_COMMAND,
        "--no-video",
        "--force-window=no",
        "--cache=yes",
        "--cache-secs=15",
        "--input-ipc-server=" + _socket_path,
        *[i["stream_url"] for i in items],
    ]

    _mpv_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _mpv_route = salida

    altavoz.activar_salida_audio(salida)

    threading.Thread(
        target=_watch,
        args=(_mpv_process,),
        daemon=True
    ).start()


def _watch(proc):
    global _mpv_process
    proc.wait()
    _mpv_process = None


# ---------------- API PUBLICA ----------------

def preparar_reproduccion(query: str):
    try:
        results = _buscar_videos(query, 3)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    for r in results:
        item = _preparar_item(r)
        if item:
            return {
                "ok": True,
                "prepared": {"items": [item]},
                "title": item["title"]
            }

    return {"ok": False, "error": "no audio found"}


def ejecutar_preparado(prepared):
    _iniciar_mpv(prepared["items"])
    return True


def reproducir(query: str):
    info = preparar_reproduccion(query)
    if not info["ok"]:
        print("error:", info["error"])
        return False

    return ejecutar_preparado(info["prepared"])


# ---------------- CONTROL BASICO ----------------

def reanudar():
    if not _mpv_alive():
        return False
    _ipc(["set_property", "pause", False])
    return True


def pausar():
    if not _mpv_alive():
        return False
    _ipc(["set_property", "pause", True])
    return True


def siguiente():
    if not _mpv_alive():
        return False
    _ipc(["playlist-next", "force"])
    return True


def anterior():
    if not _mpv_alive():
        return False
    _ipc(["playlist-prev", "force"])
    return True


def volumen(delta: int):
    if not _mpv_alive():
        return False

    vol = _ipc(["get_property", "volume"]) or 50
    new = max(0, min(100, int(vol) + delta))

    _ipc(["set_property", "volume", new])
    return True


# ---------------- IPC ----------------

def _ipc(cmd):
    payload = json.dumps({"command": cmd}).encode()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(_socket_path)
        s.sendall(payload + b"\n")
        return s.recv(4096)


# ---------------- FIX CRÍTICO (ESTO TE ROMPIA TODO) ----------------

def detener():
    """Detiene reproducción de mpv de forma segura y limpia"""
    global _mpv_process, _socket_path

    # 1. Si no hay proceso vivo, salir rápido
    if _mpv_process is None:
        return False

    try:
        # 2. Intento limpio vía IPC
        _ipc(["quit"])
    except Exception:
        pass

    try:
        # 3. Asegurar terminación del proceso
        if _mpv_process.poll() is None:
            _mpv_process.terminate()

            try:
                _mpv_process.wait(timeout=2)
            except Exception:
                _mpv_process.kill()
    except Exception:
        pass

    _mpv_process = None

    # 4. Limpieza de socket IPC (CRÍTICO en leaks)
    if _socket_path:
        try:
            if os.path.exists(_socket_path):
                os.unlink(_socket_path)
        except Exception:
            pass

    _socket_path = None

    return True