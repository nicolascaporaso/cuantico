from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import config

from .controller import TVDevice

_STATE_PATH = Path(getattr(config, "TV_STATE_PATH", Path(config.STATE_DIR) / "tvs.json"))
_DEFAULT_STATE = {
    "default_device_id": "",
    "devices": [],
}
_state = deepcopy(_DEFAULT_STATE)


def _normalize_mac(value: str = "") -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _value(device: TVDevice | dict, key: str, default=""):
    if isinstance(device, dict):
        return device.get(key, default)
    return getattr(device, key, default)


def _device_key(device: TVDevice | dict) -> str:
    brand = str(_value(device, "brand", "")).strip().lower()
    mac = _normalize_mac(_value(device, "mac", ""))
    host = str(_value(device, "host", "")).strip().lower()
    device_id = str(_value(device, "device_id", "")).strip()
    if device_id:
        return device_id
    if mac:
        return f"{brand}:{mac}"
    return f"{brand}:{host}"


def _friendly_id(brand: str, mac: str = "", host: str = "") -> str:
    norm_mac = _normalize_mac(mac)
    if norm_mac:
        return f"{brand}:{norm_mac}"
    return f"{brand}:{host.strip().lower()}"


def _hydrate(raw: dict) -> TVDevice:
    return TVDevice(
        device_id=str(raw.get("device_id") or _friendly_id(str(raw.get("brand", "tv")), str(raw.get("mac", "")), str(raw.get("host", "")))).strip(),
        brand=str(raw.get("brand", "")).strip().lower(),
        name=str(raw.get("name", "")).strip(),
        host=str(raw.get("host", "")).strip(),
        model=str(raw.get("model", "")).strip(),
        mac=_normalize_mac(raw.get("mac", "")),
        token=str(raw.get("token", "")).strip(),
        token_file=str(raw.get("token_file", "")).strip(),
        connected=bool(raw.get("connected")),
        auth_required=bool(raw.get("auth_required")),
        first_seen=str(raw.get("first_seen", "")).strip(),
        last_seen=str(raw.get("last_seen", "")).strip(),
        last_error=str(raw.get("last_error", "")).strip(),
        metadata=dict(raw.get("metadata") or {}),
    )


def _save_state():
    payload = {
        "default_device_id": _state.get("default_device_id", ""),
        "devices": [item.to_dict() for item in _state.get("devices", [])],
    }
    _STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state():
    global _state
    if not _STATE_PATH.exists():
        _state = deepcopy(_DEFAULT_STATE)
        return
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        devices = [_hydrate(item) for item in raw.get("devices", []) if isinstance(item, dict)]
        _state = {
            "default_device_id": str(raw.get("default_device_id", "")).strip(),
            "devices": devices,
        }
    except Exception:
        _state = deepcopy(_DEFAULT_STATE)


def list_devices() -> list[TVDevice]:
    return [deepcopy(item) for item in _state.get("devices", [])]


def find_device(selector: str = "") -> TVDevice | None:
    items = _state.get("devices", [])
    key = str(selector or "").strip().lower()
    norm_key = _normalize_mac(selector)
    if not items:
        return None
    if not key:
        default_id = _state.get("default_device_id", "")
        if default_id:
            for item in items:
                if item.device_id == default_id:
                    return deepcopy(item)
        return deepcopy(items[0])
    exact = [
        item for item in items
        if key in {
            item.device_id.lower(),
            item.name.lower(),
            item.host.lower(),
        }
        or (norm_key and norm_key == _normalize_mac(item.mac))
    ]
    if exact:
        return deepcopy(exact[0])
    for item in items:
        if key in item.name.lower() or key in item.host.lower():
            return deepcopy(item)
    return None


def upsert_device(device: TVDevice, make_default: bool = False) -> TVDevice:
    device.device_id = device.device_id or _device_key(device)
    current = _state.setdefault("devices", [])
    for idx, item in enumerate(current):
        if _device_key(item) == _device_key(device):
            merged = deepcopy(item)
            for field_name, value in device.to_dict().items():
                if field_name == "metadata":
                    merged.metadata.update(dict(value or {}))
                    continue
                if value not in ("", None):
                    setattr(merged, field_name, value)
            current[idx] = merged
            if make_default or not _state.get("default_device_id"):
                _state["default_device_id"] = merged.device_id
            _save_state()
            return deepcopy(merged)
    current.append(deepcopy(device))
    if make_default or not _state.get("default_device_id"):
        _state["default_device_id"] = device.device_id
    _save_state()
    return deepcopy(device)


def remove_device(selector: str) -> TVDevice | None:
    target = find_device(selector)
    if target is None:
        return None
    _state["devices"] = [item for item in _state.get("devices", []) if item.device_id != target.device_id]
    if _state.get("default_device_id") == target.device_id:
        _state["default_device_id"] = _state["devices"][0].device_id if _state["devices"] else ""
    _save_state()
    return target


def set_default(selector: str) -> TVDevice | None:
    target = find_device(selector)
    if target is None:
        return None
    _state["default_device_id"] = target.device_id
    _save_state()
    return target


load_state()
