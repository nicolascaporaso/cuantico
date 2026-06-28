import json
import re
import subprocess
import time
import unicodedata
from pathlib import Path

import config


_STATE_PATH = Path(config.STATE_DIR) / "bluetooth_audio.json"
_DEBUG_LOG_PATH = Path(config.STATE_DIR) / "unexpected-process-exit.log"


def _debug_emit(msg: str, data: dict | None = None):
    payload = {
        "sessionId": "unexpected-process-exit",
        "runId": "pre-fix",
        "hypothesisId": "BT",
        "location": "bluetooth_audio.py",
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


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return " ".join(texto.split())


def _cargar_estado() -> dict:
    if not _STATE_PATH.exists():
        return {"mode": "i2s"}
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception as e:
        _debug_emit("state-load-failed", {"error": str(e)})
    return {"mode": "i2s"}


def _guardar_estado(data: dict):
    _STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_bluetoothctl(args: list[str], timeout: int = 20) -> str:
    try:
        proc = subprocess.run(
            ["bluetoothctl", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError("bluetoothctl no está instalado. Instala bluez.") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"bluetoothctl tardó demasiado ejecutando: {' '.join(args)}") from e

    salida = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    _debug_emit("bluetoothctl-run", {"args": args, "returncode": proc.returncode, "output_preview": salida[:240]})
    return salida


def _asegurar_adaptador():
    _run_bluetoothctl(["power", "on"])
    _run_bluetoothctl(["agent", "on"])
    _run_bluetoothctl(["default-agent"])


def _parsear_devices(salida: str) -> list[dict]:
    dispositivos = []
    for linea in salida.splitlines():
        match = re.match(r"Device\s+([0-9A-F:]{17})\s+(.+)$", linea.strip(), re.I)
        if match:
            dispositivos.append({"mac": match.group(1).upper(), "name": match.group(2).strip()})
    return dispositivos


def _parsear_info(mac: str) -> dict:
    salida = _run_bluetoothctl(["info", mac], timeout=15)
    info = {
        "mac": mac.upper(),
        "name": "",
        "alias": "",
        "paired": False,
        "trusted": False,
        "connected": False,
        "blocked": False,
        "audio": False,
    }
    uuids = []
    for raw in salida.splitlines():
        linea = raw.strip()
        if linea.startswith("Name:"):
            info["name"] = linea.split(":", 1)[1].strip()
        elif linea.startswith("Alias:"):
            info["alias"] = linea.split(":", 1)[1].strip()
        elif linea.startswith("Paired:"):
            info["paired"] = linea.split(":", 1)[1].strip().lower() == "yes"
        elif linea.startswith("Trusted:"):
            info["trusted"] = linea.split(":", 1)[1].strip().lower() == "yes"
        elif linea.startswith("Connected:"):
            info["connected"] = linea.split(":", 1)[1].strip().lower() == "yes"
        elif linea.startswith("Blocked:"):
            info["blocked"] = linea.split(":", 1)[1].strip().lower() == "yes"
        elif linea.startswith("Icon:"):
            icono = linea.split(":", 1)[1].strip().lower()
            if "audio" in icono or "head" in icono:
                info["audio"] = True
        elif linea.startswith("UUID:"):
            uuids.append(linea)
    if any(token in uuid.lower() for uuid in uuids for token in ("audio sink", "a/v remote", "headset", "handsfree", "speaker")):
        info["audio"] = True
    if not info["name"]:
        info["name"] = info["alias"] or info["mac"]
    return info


def _enriquecer_devices(dispositivos: list[dict]) -> list[dict]:
    enriched = []
    for d in dispositivos:
        try:
            info = _parsear_info(d["mac"])
        except Exception as e:
            info = {
                "mac": d["mac"],
                "name": d["name"],
                "alias": d["name"],
                "paired": False,
                "trusted": False,
                "connected": False,
                "blocked": False,
                "audio": False,
                "error": str(e),
            }
        enriched.append(info)
    audio = [d for d in enriched if d.get("audio")]
    return audio or enriched


def listar_dispositivos() -> list[dict]:
    _asegurar_adaptador()
    dispositivos = _parsear_devices(_run_bluetoothctl(["devices"], timeout=10))
    return _enriquecer_devices(dispositivos)


def escanear_dispositivos(segundos: int | None = None) -> list[dict]:
    _asegurar_adaptador()
    segundos = segundos or config.BLUETOOTH_SCAN_SECONDS
    segundos = max(3, min(int(segundos), 20))
    _debug_emit("scan-start", {"seconds": segundos})
    try:
        _run_bluetoothctl(["--timeout", str(segundos), "scan", "on"], timeout=segundos + 5)
    finally:
        try:
            _run_bluetoothctl(["scan", "off"], timeout=5)
        except Exception as e:
            _debug_emit("scan-stop-failed", {"error": str(e)})
    dispositivos = listar_dispositivos()
    _debug_emit("scan-finished", {"count": len(dispositivos)})
    return dispositivos


def _resolver_dispositivo(selector: str, dispositivos: list[dict] | None = None) -> dict:
    selector = (selector or "").strip()
    if not selector:
        raise ValueError("faltó el nombre o la MAC del parlante")
    dispositivos = dispositivos or listar_dispositivos()
    selector_norm = _normalizar(selector)

    exact_mac = next((d for d in dispositivos if d["mac"].lower() == selector.lower()), None)
    if exact_mac:
        return exact_mac

    exact_name = next((d for d in dispositivos if _normalizar(d.get("name", "")) == selector_norm), None)
    if exact_name:
        return exact_name

    contains = [d for d in dispositivos if selector_norm in _normalizar(d.get("name", "")) or selector_norm in d["mac"].lower()]
    if len(contains) == 1:
        return contains[0]
    if len(contains) > 1:
        opciones = ", ".join(f"{d['name']} ({d['mac']})" for d in contains[:5])
        raise ValueError(f"hay varios dispositivos posibles: {opciones}")
    raise ValueError(f"no encontré ningún parlante Bluetooth que coincida con '{selector}'")


def conectar_dispositivo(selector: str) -> dict:
    _asegurar_adaptador()
    dispositivos = escanear_dispositivos()
    dispositivo = _resolver_dispositivo(selector, dispositivos)
    mac = dispositivo["mac"]

    _run_bluetoothctl(["trust", mac], timeout=20)
    pair_output = _run_bluetoothctl(["pair", mac], timeout=45)
    connect_output = _run_bluetoothctl(["connect", mac], timeout=45)
    info = _parsear_info(mac)

    if not info.get("connected"):
        raise RuntimeError(
            f"Bluetooth conectado a medias. Pair: {pair_output[:120]} | Connect: {connect_output[:120]}"
        )

    estado = {
        "mode": "bluetooth",
        "mac": mac,
        "name": info.get("name") or dispositivo.get("name") or mac,
        "preferred_name": info.get("name") or dispositivo.get("name") or mac,
        "preferred_mac": mac,
        "profile": config.BLUETOOTH_AUDIO_PROFILE,
        "connected_at": config.now_local().isoformat(),
    }
    _guardar_estado(estado)
    _debug_emit("device-connected", estado)
    return estado


def usar_altavoz_integrado() -> dict:
    estado_anterior = _cargar_estado()
    mac = estado_anterior.get("mac", "")
    if mac:
        try:
            _run_bluetoothctl(["disconnect", mac], timeout=20)
        except Exception as e:
            _debug_emit("disconnect-failed", {"mac": mac, "error": str(e)})
    estado = {"mode": "i2s", "updated_at": config.now_local().isoformat()}
    if estado_anterior.get("preferred_name"):
        estado["preferred_name"] = estado_anterior["preferred_name"]
    if estado_anterior.get("preferred_mac"):
        estado["preferred_mac"] = estado_anterior["preferred_mac"]
    _guardar_estado(estado)
    _debug_emit("route-restored-i2s", estado)
    return estado


def desconectar_dispositivo(selector: str) -> dict:
    dispositivos = listar_dispositivos()
    dispositivo = _resolver_dispositivo(selector, dispositivos)
    mac = dispositivo["mac"]
    _run_bluetoothctl(["disconnect", mac], timeout=20)

    estado_anterior = _cargar_estado()
    estado = {"mode": "i2s", "updated_at": config.now_local().isoformat()}
    if estado_anterior.get("preferred_name"):
        estado["preferred_name"] = estado_anterior["preferred_name"]
    if estado_anterior.get("preferred_mac"):
        estado["preferred_mac"] = estado_anterior["preferred_mac"]
    if estado_anterior.get("mac") and estado_anterior.get("mac", "").upper() != mac:
        estado["mode"] = estado_anterior.get("mode", "i2s")
        estado["mac"] = estado_anterior["mac"]
        estado["name"] = estado_anterior.get("name", estado_anterior["mac"])
        estado["profile"] = estado_anterior.get("profile", config.BLUETOOTH_AUDIO_PROFILE)
    _guardar_estado(estado)
    _debug_emit("device-disconnected", {"mac": mac, "name": dispositivo.get("name", mac)})
    return {"mac": mac, "name": dispositivo.get("name", mac)}


def dispositivo_conectado() -> dict:
    salida = obtener_salida_activa()
    estado = _cargar_estado()
    return {
        "active_kind": salida["kind"],
        "active_label": salida["label"],
        "active_mac": salida.get("mac", ""),
        "preferred_name": estado.get("preferred_name", ""),
        "preferred_mac": estado.get("preferred_mac", ""),
        "local_device": config.ALSA_PLAYBACK_DEVICE,
    }


def obtener_salida_activa() -> dict:
    estado = _cargar_estado()
    if estado.get("mode") != "bluetooth" or not config.BLUETOOTH_AUTO_ROUTE:
        return {
            "kind": "alsa_local",
            "device": config.ALSA_PLAYBACK_DEVICE,
            "label": "I2S/VoiceHAT",
            "needs_gpio": True,
        }

    mac = (estado.get("mac") or "").upper()
    if not mac:
        return {
            "kind": "alsa_local",
            "device": config.ALSA_PLAYBACK_DEVICE,
            "label": "I2S/VoiceHAT",
            "needs_gpio": True,
        }

    try:
        info = _parsear_info(mac)
    except Exception as e:
        _debug_emit("active-output-info-failed", {"mac": mac, "error": str(e)})
        return {
            "kind": "alsa_local",
            "device": config.ALSA_PLAYBACK_DEVICE,
            "label": "I2S/VoiceHAT",
            "needs_gpio": True,
        }

    if info.get("connected"):
        return {
            "kind": "bluetooth",
            "device": f"bluealsa:DEV={mac},PROFILE={config.BLUETOOTH_AUDIO_PROFILE}",
            "label": info.get("name") or mac,
            "needs_gpio": False,
            "mac": mac,
        }

    return {
        "kind": "alsa_local",
        "device": config.ALSA_PLAYBACK_DEVICE,
        "label": "I2S/VoiceHAT",
        "needs_gpio": True,
    }


def resumen_salida_activa() -> str:
    salida = obtener_salida_activa()
    estado = _cargar_estado()
    if salida["kind"] == "bluetooth":
        base = f"Bluetooth: {salida['label']} ({salida['mac']})"
    else:
        base = f"I2S local: {salida['device']}"
    if estado.get("preferred_name"):
        return f"{base}. Preferido: {estado['preferred_name']} ({estado.get('preferred_mac', 'sin MAC')})"
    return base
