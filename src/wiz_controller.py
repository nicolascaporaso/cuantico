import asyncio
import contextlib
import json
import threading
import time
from copy import deepcopy
from pathlib import Path

import config
import cuantico_profiles as profile

try:
    from pywizlight import PilotBuilder, discovery, wizlight
except Exception as e:  # pragma: no cover - depende del entorno real
    PilotBuilder = None
    discovery = None
    wizlight = None
    _IMPORT_ERROR = str(e)
else:
    _IMPORT_ERROR = ""


_STATE_PATH = Path(config.STATE_DIR) / "wiz_lights.json"
_DEFAULT_STATE = {
    "lights": [],
    "emotion_sync": {
        "enabled": False,
        "selector": "",
    },
}
_state = deepcopy(_DEFAULT_STATE)
_last_discovery: list[dict] = []
_effect_lock = threading.Lock()
_effect_thread: threading.Thread | None = None
_effect_stop: threading.Event | None = None


def _now_iso() -> str:
    return config.now_local().isoformat()


def _load_state():
    global _state
    if not _STATE_PATH.exists():
        _state = deepcopy(_DEFAULT_STATE)
        return
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("wiz_lights.json debe contener un objeto")
        _state = deepcopy(_DEFAULT_STATE)
        _state["lights"] = raw.get("lights", [])
        if isinstance(raw.get("emotion_sync"), dict):
            _state["emotion_sync"].update(raw["emotion_sync"])
    except Exception:
        _state = deepcopy(_DEFAULT_STATE)


def _save_state():
    _STATE_PATH.write_text(json.dumps(_state, ensure_ascii=False, indent=2), encoding="utf-8")


def _run(awaitable):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(awaitable)
    finally:
        loop.close()


def disponible() -> tuple[bool, str]:
    if _IMPORT_ERROR:
        return False, f"pywizlight no está disponible ({_IMPORT_ERROR})"
    return True, "wiz listo"


def _brightness_to_byte(pct: int) -> int:
    pct = max(0, min(100, int(pct)))
    return int(round((pct / 100.0) * 255))


def _brightness_from_byte(value) -> int:
    if value is None:
        return 0
    try:
        return max(0, min(100, int(round((int(value) / 255.0) * 100))))
    except Exception:
        return 0


def _find_registered_by_ip(ip: str) -> dict | None:
    for entry in _state["lights"]:
        if entry.get("ip") == ip:
            return entry
    return None


def _friendly_name(ip: str) -> str:
    last = ip.split(".")[-1] if ip else "wiz"
    return f"wiz-{last}"


def _match_selector(items: list[dict], selector: str) -> list[dict]:
    key = (selector or "").strip().lower()
    if not key:
        return items
    exact = [
        item for item in items
        if key in {
            str(item.get("ip", "")).lower(),
            str(item.get("name", "")).lower(),
        }
    ]
    if exact:
        return exact
    partial = []
    for item in items:
        if (
            key in str(item.get("name", "")).lower()
            or key in str(item.get("ip", "")).lower()
            or str(item.get("name", "")).lower() in key
        ):
            partial.append(item)
    return partial


def _resolve_registered(selector: str = "") -> list[dict]:
    items = list(_state["lights"])
    if not items:
        return []
    return _match_selector(items, selector)


def _resolve_discovery_or_registered(selector: str) -> dict | None:
    if not selector:
        return None
    for collection in (_last_discovery, _state["lights"]):
        matched = _match_selector(list(collection), selector)
        if matched:
            return matched[0]
    return None


async def _discover_async() -> list:
    finder = getattr(discovery, "discover_lights", None) or getattr(discovery, "find_wizlights", None)
    if finder is None:
        raise RuntimeError("la versión instalada de pywizlight no soporta discovery")
    kwargs = {}
    if getattr(config, "WIZ_BROADCAST_SPACE", ""):
        kwargs["broadcast_space"] = config.WIZ_BROADCAST_SPACE
    try:
        if kwargs:
            return await finder(**kwargs)
        return await finder()
    except TypeError:
        if kwargs:
            return await finder(discovery, **kwargs)
        return await finder(discovery)


async def _fetch_state_async(ip: str) -> dict:
    light = wizlight(ip)
    state = await light.updateState()
    rgb = state.get_rgb() if hasattr(state, "get_rgb") else None
    return {
        "ip": ip,
        "is_on": bool(state.get_state()) if hasattr(state, "get_state") else False,
        "brightness": _brightness_from_byte(state.get_brightness() if hasattr(state, "get_brightness") else None),
        "rgb": list(rgb) if rgb else [],
        "scene": state.get_scene() if hasattr(state, "get_scene") else "",
        "colortemp": state.get_colortemp() if hasattr(state, "get_colortemp") else None,
    }


async def _turn_on_async(ip: str, builder=None):
    light = wizlight(ip)
    if builder is None:
        await light.turn_on(PilotBuilder())
    else:
        await light.turn_on(builder)


async def _turn_off_async(ip: str):
    light = wizlight(ip)
    await light.turn_off()


async def _apply_builder_many(entries: list[dict], builder=None, turn_off: bool = False):
    tasks = []
    for entry in entries:
        ip = entry["ip"]
        if turn_off:
            tasks.append(_turn_off_async(ip))
        else:
            tasks.append(_turn_on_async(ip, builder))
    return await asyncio.gather(*tasks, return_exceptions=True)


def _apply_many(entries: list[dict], builder=None, turn_off: bool = False) -> bool:
    if not entries:
        return False
    results = _run(_apply_builder_many(entries, builder=builder, turn_off=turn_off))
    ok = True
    for result in results:
        if isinstance(result, Exception):
            ok = False
    return ok


def _stop_effect():
    global _effect_thread, _effect_stop
    with _effect_lock:
        stop = _effect_stop
        thread = _effect_thread
        _effect_stop = None
        _effect_thread = None
    if stop:
        stop.set()
    if thread and thread.is_alive():
        thread.join(timeout=1.0)


def inicializar():
    _load_state()
    ok, reason = disponible()
    if not ok:
        print(f"⚠️ WiZ no disponible: {reason}")
        return False
    if _state["lights"]:
        print("💡 WiZ: " + ", ".join(item["name"] for item in _state["lights"]))
    return True


def buscar_luces() -> list[dict]:
    ok, reason = disponible()
    if not ok:
        raise RuntimeError(reason)
    bulbs = _run(_discover_async())
    found = []
    for bulb in bulbs or []:
        ip = getattr(bulb, "ip", "") or getattr(bulb, "ip_address", "")
        if not ip:
            continue
        existing = _find_registered_by_ip(ip)
        found.append({
            "ip": str(ip),
            "name": existing.get("name") if existing else _friendly_name(str(ip)),
            "known": bool(existing),
            "last_seen": _now_iso(),
        })
    global _last_discovery
    _last_discovery = found
    return found


def agregar_luz(selector: str, nombre: str = "") -> dict:
    ok, reason = disponible()
    if not ok:
        raise RuntimeError(reason)
    ref = _resolve_discovery_or_registered(selector) or {"ip": selector.strip(), "name": nombre.strip()}
    ip = ref.get("ip", "").strip()
    if not ip:
        raise ValueError("necesito una IP o una luz descubierta para agregar")
    try:
        state = _run(_fetch_state_async(ip))
    except Exception as e:
        raise RuntimeError(f"no pude hablar con la luz WiZ {ip}: {e}") from e
    entry = _find_registered_by_ip(ip)
    if entry is None:
        entry = {
            "ip": ip,
            "name": nombre.strip() or ref.get("name") or _friendly_name(ip),
            "added_at": _now_iso(),
        }
        _state["lights"].append(entry)
    elif nombre.strip():
        entry["name"] = nombre.strip()
    entry["last_seen"] = _now_iso()
    entry["last_state"] = state
    _save_state()
    return deepcopy(entry)


def renombrar_luz(selector: str, nombre_nuevo: str) -> dict:
    if not nombre_nuevo.strip():
        raise ValueError("el nombre nuevo no puede estar vacío")
    matched = _resolve_registered(selector)
    if not matched:
        raise ValueError("no encontré esa luz WiZ")
    entry = matched[0]
    entry["name"] = nombre_nuevo.strip()
    _save_state()
    return deepcopy(entry)


def listar_luces() -> list[dict]:
    lights = []
    for entry in _state["lights"]:
        item = deepcopy(entry)
        if _state["emotion_sync"]["enabled"]:
            selector = _state["emotion_sync"].get("selector", "")
            item["emotion_sync"] = not selector or bool(_match_selector([entry], selector))
        else:
            item["emotion_sync"] = False
        lights.append(item)
    return lights


def nombres_luces() -> list[str]:
    return [entry["name"] for entry in _state["lights"]]


def _require_targets(selector: str = "") -> list[dict]:
    entries = _resolve_registered(selector)
    if not entries:
        raise ValueError("no encontré luces WiZ registradas con ese nombre")
    return entries


def encender(selector: str = "") -> bool:
    _stop_effect()
    return _apply_many(_require_targets(selector))


def apagar(selector: str = "") -> bool:
    _stop_effect()
    return _apply_many(_require_targets(selector), turn_off=True)


def cambiar_color(r: int, g: int, b: int, selector: str = "", brillo: int | None = None) -> bool:
    _stop_effect()
    builder = PilotBuilder(
        rgb=(max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b)))),
        brightness=_brightness_to_byte(brillo if brillo is not None else 100),
    )
    return _apply_many(_require_targets(selector), builder=builder)


def fijar_brillo(porcentaje: int, selector: str = "") -> bool:
    _stop_effect()
    builder = PilotBuilder(brightness=_brightness_to_byte(porcentaje))
    return _apply_many(_require_targets(selector), builder=builder)


def ajustar_brillo(delta: int, selector: str = "") -> bool:
    _stop_effect()
    entries = _require_targets(selector)
    ok_total = True
    for entry in entries:
        try:
            state = _run(_fetch_state_async(entry["ip"]))
            actual = state.get("brightness", 50)
            nuevo = max(1, min(100, int(actual) + int(delta)))
            ok = _apply_many([entry], builder=PilotBuilder(brightness=_brightness_to_byte(nuevo)))
            ok_total = ok_total and ok
        except Exception:
            ok_total = False
    return ok_total


def modo_lectura(selector: str = "") -> bool:
    _stop_effect()
    builder = PilotBuilder(colortemp=4200, brightness=_brightness_to_byte(72))
    return _apply_many(_require_targets(selector), builder=builder)


def _effect_frames(name: str):
    if name == "arcoiris":
        return [
            ((255, 0, 0), 100, 0.25),
            ((255, 140, 0), 100, 0.25),
            ((255, 255, 0), 100, 0.25),
            ((0, 255, 0), 100, 0.25),
            ((0, 170, 255), 100, 0.25),
            ((0, 0, 255), 100, 0.25),
            ((180, 0, 255), 100, 0.25),
        ]
    if name == "policia":
        return [
            ((255, 0, 0), 100, 0.18),
            ((0, 0, 0), 0, 0.08),
            ((0, 0, 255), 100, 0.18),
            ((0, 0, 0), 0, 0.08),
        ]
    if name == "respirar":
        return [
            ((255, 180, 120), 18, 0.35),
            ((255, 180, 120), 45, 0.35),
            ((255, 180, 120), 80, 0.35),
            ((255, 180, 120), 45, 0.35),
        ]
    if name == "parpadeo":
        return [
            ((255, 255, 255), 100, 0.25),
            ((0, 0, 0), 0, 0.15),
        ]
    return [
        ((255, 0, 200), 100, 0.18),
        ((0, 140, 255), 100, 0.18),
        ((0, 255, 120), 100, 0.18),
        ((255, 255, 255), 100, 0.12),
    ]


def _run_effect(entries: list[dict], frames: list[tuple[tuple[int, int, int], int, float]], stop_event: threading.Event, duration_s: int):
    started = time.time()
    while not stop_event.is_set():
        if duration_s > 0 and time.time() - started >= duration_s:
            break
        for rgb, brightness, pause_s in frames:
            if stop_event.is_set():
                break
            if brightness <= 0:
                _apply_many(entries, turn_off=True)
            else:
                _apply_many(entries, builder=PilotBuilder(rgb=rgb, brightness=_brightness_to_byte(brightness)))
            stop_event.wait(pause_s)


def efecto(nombre: str = "fiesta", selector: str = "", segundos: int = 30) -> bool:
    entries = _require_targets(selector)
    name = (nombre or "fiesta").strip().lower()
    alias = {
        "fiesta": "fiesta",
        "party": "fiesta",
        "arcoiris": "arcoiris",
        "rainbow": "arcoiris",
        "policia": "policia",
        "leer": "respirar",
        "respirar": "respirar",
        "parpadeo": "parpadeo",
        "blink": "parpadeo",
    }
    frames = _effect_frames(alias.get(name, "fiesta"))
    _stop_effect()
    global _effect_thread, _effect_stop
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_effect,
        args=(entries, frames, stop_event, max(0, int(segundos))),
        daemon=True,
        name="wiz-effect",
    )
    with _effect_lock:
        _effect_stop = stop_event
        _effect_thread = thread
    thread.start()
    return True


def parpadear(selector: str = "", segundos: int = 30) -> bool:
    return efecto("parpadeo", selector=selector, segundos=segundos)


def _state_to_action(state_name: str) -> tuple[str, dict]:
    cfg = profile.get_light_state(state_name)
    effect = cfg.get("effect", "pulse")
    color = tuple(cfg.get("color", (255, 255, 255)))
    brightness = max(12, min(100, int(cfg.get("max_factor", 1.0) * 100)))
    if effect == "off":
        return "off", {}
    if effect == "rainbow":
        return "effect", {"nombre": "arcoiris", "segundos": 0}
    if effect == "blink":
        return "effect", {"nombre": "parpadeo", "segundos": 0}
    if effect == "flicker":
        return "effect", {"nombre": "fiesta", "segundos": 0}
    return "color", {"rgb": color, "brightness": brightness}


def activar_sync_emociones(selector: str = "") -> bool:
    _state["emotion_sync"]["enabled"] = True
    _state["emotion_sync"]["selector"] = selector.strip()
    _save_state()
    return True


def desactivar_sync_emociones() -> bool:
    _state["emotion_sync"]["enabled"] = False
    _state["emotion_sync"]["selector"] = ""
    _save_state()
    _stop_effect()
    return True


def sync_activo() -> bool:
    return bool(_state["emotion_sync"].get("enabled"))


def sincronizar_estado_si_activo(state_name: str):
    if not sync_activo():
        return
    selector = _state["emotion_sync"].get("selector", "")
    try:
        accion, payload = _state_to_action(state_name)
        if accion == "off":
            apagar(selector)
        elif accion == "effect":
            efecto(payload["nombre"], selector=selector, segundos=payload["segundos"])
        else:
            rgb = payload["rgb"]
            cambiar_color(rgb[0], rgb[1], rgb[2], selector=selector, brillo=payload["brightness"])
    except Exception:
        return


def resumen_estado() -> str:
    luces = listar_luces()
    if not luces:
        return "no hay luces WiZ registradas"
    nombres = ", ".join(f"{item['name']} ({item['ip']})" for item in luces)
    if sync_activo():
        selector = _state["emotion_sync"].get("selector", "")
        if selector:
            return f"WiZ registradas: {nombres}. Sync emocional activo para {selector}"
        return f"WiZ registradas: {nombres}. Sync emocional activo para todas"
    return f"WiZ registradas: {nombres}. Sync emocional apagado"


def estado_actual(selector: str = "") -> list[dict]:
    entries = _require_targets(selector)
    resultados = []
    for entry in entries:
        estado = _run(_fetch_state_async(entry["ip"]))
        estado["name"] = entry["name"]
        resultados.append(estado)
    return resultados
