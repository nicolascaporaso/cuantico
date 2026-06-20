import requests
import config

BASE_URL = "https://developer-api.govee.com/v1"
HEADERS = {"Govee-API-Key": config.GOVEE_API_KEY, "Content-Type": "application/json"}

_dispositivos = []


def inicializar():
    """Descubre las luces Govee enlazadas a la cuenta."""
    global _dispositivos
    try:
        r = requests.get(f"{BASE_URL}/devices", headers=HEADERS, timeout=5)
        if r.status_code != 200:
            print(f"⚠️ Govee: error {r.status_code} listando dispositivos. Body: {r.text}")
            return
        data = r.json().get("data", {}).get("devices", [])
        _dispositivos = []
        for d in data:
            name = d.get("deviceName", "?")
            model = d.get("model", "?")
            controllable = d.get("controllable", False)
            retrievable = d.get("retrievable", False)
            cmds = d.get("supportCmds", [])
            print(f"   · {name} | modelo={model} | controllable={controllable} | retrievable={retrievable} | cmds={cmds}")
            if controllable and "turn" in cmds:
                _dispositivos.append({"device": d["device"], "model": model, "name": name})
        if _dispositivos:
            print(f"💡 Govee: {len(_dispositivos)} luz(ces) controlable(s): " +
                  ", ".join(d["name"] for d in _dispositivos))
        else:
            print("💡 Govee: ninguna luz controlable por la Developer API v1.")
    except Exception as e:
        print(f"⚠️ Govee no disponible: {e}")


def _enviar(device, model, valor):
    payload = {"device": device, "model": model, "cmd": {"name": "turn", "value": valor}}
    try:
        r = requests.put(f"{BASE_URL}/devices/control", headers=HEADERS, json=payload, timeout=5)
        print(f"   → Govee {device[-6:]} {valor}: HTTP {r.status_code} | {r.text[:200]}")
        if r.status_code != 200:
            return False
        body = r.json()
        return body.get("code") == 200
    except Exception as e:
        print(f"⚠️ Govee error: {e}")
        return False


def nombres_luces():
    return [d["name"] for d in _dispositivos]


def _filtrar(nombre=None):
    """Devuelve los dispositivos que casan con `nombre` (case-insensitive, contains). None = todas."""
    if not nombre:
        return _dispositivos
    low = nombre.lower().strip()
    matched = [d for d in _dispositivos if low in d["name"].lower() or d["name"].lower() in low]
    return matched


def _accion_todas(valor, nombre=None):
    devs = _filtrar(nombre)
    if not devs:
        return False
    ok = 0
    for d in devs:
        if _enviar(d["device"], d["model"], valor):
            ok += 1
    return ok == len(devs)


def encender_todas(nombre=None):
    return _accion_todas("on", nombre)


def apagar_todas(nombre=None):
    return _accion_todas("off", nombre)


def _enviar_cmd(device, model, cmd):
    """cmd = dict con {name, value}. Permite mandar 'color', 'brightness', etc."""
    payload = {"device": device, "model": model, "cmd": cmd}
    try:
        r = requests.put(f"{BASE_URL}/devices/control", headers=HEADERS, json=payload, timeout=5)
        print(f"   → Govee {device[-6:]} {cmd['name']}={cmd['value']}: HTTP {r.status_code} | {r.text[:200]}")
        if r.status_code != 200:
            return False
        return r.json().get("code") == 200
    except Exception as e:
        print(f"⚠️ Govee error: {e}")
        return False


def cambiar_color_todas(r, g, b, nombre=None):
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    devs = _filtrar(nombre)
    if not devs:
        return False
    ok = 0
    for d in devs:
        # Si la bombilla está apagada, Govee acepta el color pero no lo aplica
        # hasta encender. Forzamos ON antes (idempotente si ya estaba ON).
        _enviar(d["device"], d["model"], "on")
        if _enviar_cmd(d["device"], d["model"], {"name": "color", "value": {"r": r, "g": g, "b": b}}):
            ok += 1
    return ok == len(devs)


def cambiar_brillo_todas(pct, nombre=None):
    """pct: 0-100"""
    pct = max(0, min(100, int(pct)))
    devs = _filtrar(nombre)
    if not devs:
        return False
    ok = 0
    for d in devs:
        # Mismo caso que color: encender antes de tocar brillo.
        _enviar(d["device"], d["model"], "on")
        if _enviar_cmd(d["device"], d["model"], {"name": "brightness", "value": pct}):
            ok += 1
    return ok == len(devs)
