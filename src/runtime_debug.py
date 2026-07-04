import threading
import time
import traceback
import sys
from pathlib import Path

import config


_DUMP_LOG_PATH = Path(config.STATE_DIR) / "thread-dumps.log"
_state_lock = threading.Lock()
_operations: dict[str, dict] = {}
_heartbeats: dict[str, dict] = {}
_watchdog_started = False


def heartbeat(component: str, data: dict | None = None):
    now = time.time()
    with _state_lock:
        _heartbeats[component] = {
            "component": component,
            "ts": now,
            "thread": threading.current_thread().name,
            "data": dict(data or {}),
        }


def snapshot_heartbeats() -> list[dict]:
    now = time.time()
    with _state_lock:
        items = list(_heartbeats.values())
    return [
        {
            "component": item["component"],
            "age_sec": round(max(0.0, now - float(item["ts"])), 3),
            "thread": item["thread"],
            "data": item["data"],
        }
        for item in sorted(items, key=lambda row: row["component"])
    ]


def mark_operation_start(name: str, data: dict | None = None) -> str:
    token = f"{name}:{time.time_ns()}:{threading.get_ident()}"
    with _state_lock:
        _operations[token] = {
            "name": name,
            "start": time.time(),
            "thread": threading.current_thread().name,
            "data": dict(data or {}),
        }
    return token


def mark_operation_end(token: str, data: dict | None = None) -> dict | None:
    with _state_lock:
        info = _operations.pop(token, None)
    if not info:
        return None
    end_ts = time.time()
    result = {
        "name": info["name"],
        "thread": info["thread"],
        "duration_sec": round(max(0.0, end_ts - float(info["start"])), 3),
        "data": info["data"],
    }
    if data:
        result["result"] = dict(data)
    return result


def snapshot_operations() -> list[dict]:
    now = time.time()
    with _state_lock:
        items = list(_operations.values())
    return [
        {
            "name": item["name"],
            "thread": item["thread"],
            "elapsed_sec": round(max(0.0, now - float(item["start"])), 3),
            "data": item["data"],
        }
        for item in sorted(items, key=lambda row: (row["name"], row["thread"]))
    ]


def dump_threads(reason: str = "manual", extra: dict | None = None) -> str:
    now_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    frames = sys._current_frames()
    thread_map = {thread.ident: thread for thread in threading.enumerate()}
    parts = [f"=== thread dump: {reason} @ {now_text} ==="]
    if extra:
        parts.append(f"extra={extra}")
    for ident, frame in frames.items():
        thread = thread_map.get(ident)
        thread_name = thread.name if thread else f"thread-{ident}"
        parts.append(f"\n--- {thread_name} ({ident}) ---")
        parts.extend(traceback.format_stack(frame))
    dump_text = "\n".join(parts).rstrip() + "\n"
    try:
        _DUMP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DUMP_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(dump_text)
            fh.write("\n")
    except Exception:
        pass
    return dump_text


def start_watchdog(debug_emit, *, interval_sec: float = 30.0, slow_after_sec: float = 20.0):
    global _watchdog_started
    with _state_lock:
        if _watchdog_started:
            return
        _watchdog_started = True

    def _run():
        while True:
            try:
                threads = [thread.name for thread in threading.enumerate()]
                operations = snapshot_operations()
                heartbeats = snapshot_heartbeats()
                debug_emit(
                    "thread-health",
                    {
                        "threads": threads,
                        "active_operations": operations,
                        "heartbeats": heartbeats,
                    },
                )
                slow_ops = [op for op in operations if op["elapsed_sec"] >= slow_after_sec]
                if slow_ops:
                    dump_text = dump_threads(
                        "slow-operation",
                        {"slow_operations": slow_ops, "threads": threads},
                    )
                    debug_emit(
                        "thread-dump",
                        {
                            "reason": "slow-operation",
                            "slow_operations": slow_ops,
                            "dump_preview": dump_text[-12000:],
                        },
                    )
            except Exception as exc:
                try:
                    debug_emit("thread-watchdog-error", {"error": str(exc)})
                except Exception:
                    pass
            time.sleep(interval_sec)

    threading.Thread(target=_run, name="runtime-watchdog", daemon=True).start()
