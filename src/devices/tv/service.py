from __future__ import annotations

import asyncio
import ipaddress
import re
from copy import deepcopy

import config

from .controller import TVCommandResult, TVDevice, error_result, ok_result
from . import registry
from .samsung import SamsungTVController

_BACKENDS = {
    "samsung": SamsungTVController,
}


def _run(awaitable):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(awaitable)
    finally:
        loop.close()


def inicializar():
    registry.load_state()


def _controller_for(device: TVDevice):
    backend = _BACKENDS.get(device.brand)
    if backend is None:
        raise RuntimeError(f"no tengo backend para la marca {device.brand}")
    return backend(deepcopy(device))


def _save_controller_device(controller) -> TVDevice:
    return registry.upsert_device(controller.device)


def _normalize_ip_like(selector: str) -> str:
    """Convierte cosas como '192, 168, 1 40' o '192 168 1 40' en '192.168.1.40'.

    El STT (Deepgram) suele transcribir una IP dictada en voz alta con comas
    y espacios en vez de puntos. Si no se normaliza, _is_ip_selector() falla
    y bind_device() nunca usa el atajo directo discover_host(ip), cayendo
    en el escaneo genérico de red (SSDP + subred) que puede no encontrar el TV.
    """
    text = str(selector or "").strip()
    if not text:
        return text
    digit_groups = re.findall(r"\d+", text)
    if len(digit_groups) == 4 and all(0 <= int(g) <= 255 for g in digit_groups):
        candidate = ".".join(digit_groups)
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            pass
    return text


def _resolve_device(selector: str = "", auto_discover: bool = True) -> TVDevice | None:
    selector = _normalize_ip_like(selector)
    device = registry.find_device(selector)
    if device is not None:
        return device
    if not auto_discover:
        return None
    discover(timeout_s=float(getattr(config, "TV_DISCOVERY_TIMEOUT_S", 4.0)))
    return registry.find_device(selector)


def _is_ip_selector(selector: str) -> bool:
    try:
        ipaddress.ip_address(str(selector or "").strip())
        return True
    except ValueError:
        return False


def _execute(selector: str, method_name: str, *args) -> TVCommandResult:
    device = _resolve_device(selector)
    if device is None:
        return error_result("no encontré ningún TV registrado")
    controller = _controller_for(device)
    method = getattr(controller, method_name)
    result = _run(method(*args))
    _save_controller_device(controller)
    return result


def discover(timeout_s: float | None = None) -> TVCommandResult:
    timeout = float(timeout_s or getattr(config, "TV_DISCOVERY_TIMEOUT_S", 4.0))
    found: list[dict] = []
    for backend in _BACKENDS.values():
        for device in _run(backend.discover(timeout)):
            registry.upsert_device(device)
            found.append(device.to_dict())
    if not found:
        return error_result("no encontré TVs compatibles en la red", devices=[])
    return ok_result("tvs descubiertos", devices=found, count=len(found))


def list_devices(refresh: bool = False) -> TVCommandResult:
    if refresh:
        discover()
    devices = [item.to_dict() for item in registry.list_devices()]
    online = sum(1 for item in devices if item.get("connected"))
    return ok_result(
        "ok",
        devices=devices,
        count=len(devices),
        online=online,
        default_device_id=(registry.find_device("").device_id if registry.find_device("") else ""),
    )


def bind_device(selector: str, name: str = "") -> TVCommandResult:
    selector = _normalize_ip_like(selector)
    device = _resolve_device(selector)
    if device is None:
        if _is_ip_selector(selector):
            for backend in _BACKENDS.values():
                discover_host = getattr(backend, "discover_host", None)
                if callable(discover_host):
                    device = _run(discover_host(str(selector).strip()))
                    if device is not None:
                        break
        result = discover() if device is None else None
        if device is None and result is not None and not result.ok:
            return result
        if device is None:
            device = _resolve_device(selector, auto_discover=False)
    if device is None:
        return error_result("no encontré ese TV para vincular")
    if name.strip():
        device.name = name.strip()
    saved = registry.upsert_device(device, make_default=True)
    controller = _controller_for(saved)
    connect_result = _run(controller.connect())
    _save_controller_device(controller)
    return TVCommandResult(
        connect_result.ok,
        connect_result.message,
        {
            **connect_result.data,
            "device": controller.device.to_dict(),
        },
    )


def forget_device(selector: str) -> TVCommandResult:
    removed = registry.remove_device(selector)
    if removed is None:
        return error_result("no encontré ese TV registrado")
    return ok_result("tv eliminado", device=removed.to_dict())


def set_default(selector: str) -> TVCommandResult:
    device = registry.set_default(selector)
    if device is None:
        return error_result("no encontré ese TV para dejar por defecto")
    return ok_result("tv por defecto actualizado", device=device.to_dict())


def get_status(selector: str = "") -> TVCommandResult:
    return _execute(selector, "get_status")


def power_on(selector: str = "") -> TVCommandResult:
    return _execute(selector, "power_on")


def power_off(selector: str = "") -> TVCommandResult:
    return _execute(selector, "power_off")


def volume_up(selector: str = "") -> TVCommandResult:
    return _execute(selector, "volume_up")


def volume_down(selector: str = "") -> TVCommandResult:
    return _execute(selector, "volume_down")


def set_volume(level: int, selector: str = "") -> TVCommandResult:
    return _execute(selector, "set_volume", level)


def mute(selector: str = "") -> TVCommandResult:
    return _execute(selector, "mute")


def unmute(selector: str = "") -> TVCommandResult:
    return _execute(selector, "unmute")


def launch_app(app_name: str, selector: str = "") -> TVCommandResult:
    return _execute(selector, "launch_app", app_name)


def send_key(key: str, selector: str = "") -> TVCommandResult:
    return _execute(selector, "send_key", key)