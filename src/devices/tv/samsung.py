from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
import config

from .controller import (
    TVController,
    TVDevice,
    TVOfflineError,
    TVTimeoutError,
    TVUnauthorizedError,
    error_result,
    ok_result,
)

try:
    from samsungtvws import SamsungTVWS
except Exception as exc:  # pragma: no cover - depende del entorno real
    SamsungTVWS = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""


_REMOTE_NAME = getattr(config, "TV_CLIENT_NAME", "Cuantico")
_DISCOVERY_TIMEOUT = float(getattr(config, "TV_DISCOVERY_TIMEOUT_S", 4.0))
_CONNECT_TIMEOUT = float(getattr(config, "TV_CONNECT_TIMEOUT_S", 5.0))
_TOKEN_DIR = Path(config.STATE_DIR) / "tv_tokens"
_TOKEN_DIR.mkdir(exist_ok=True)
_WS_PORTS = (8002, 8001)
_SCAN_SUBNET = bool(getattr(config, "TV_DISCOVERY_SCAN_SUBNET", True))
_DISCOVERY_HOSTS = [item.strip() for item in str(getattr(config, "TV_DISCOVERY_HOSTS", "") or "").split(",") if item.strip()]

_SSDP_TARGETS = (
    "ssdp:all",
    "urn:samsung.com:device:RemoteControlReceiver:1",
    "urn:dial-multiscreen-org:service:dial:1",
)

_APP_ALIASES = {
    "youtube": ["111299001912"],
    "netflix": ["3201907018807", "11101200001"],
    "disney+": ["3202204027038", "3202009021709", "3201901017640"],
    "disney plus": ["3202204027038", "3202009021709", "3201901017640"],
    "disney": ["3202204027038", "3202009021709", "3201901017640"],
}

_KEY_ALIASES = {
    "home": "KEY_HOME",
    "atras": "KEY_RETURN",
    "back": "KEY_RETURN",
    "ok": "KEY_ENTER",
    "enter": "KEY_ENTER",
    "arriba": "KEY_UP",
    "abajo": "KEY_DOWN",
    "izquierda": "KEY_LEFT",
    "derecha": "KEY_RIGHT",
    "mute": "KEY_MUTE",
    "source": "KEY_SOURCE",
    "hdmi": "KEY_HDMI",
    "hdmi1": "KEY_HDMI1",
    "hdmi 1": "KEY_HDMI1",
    "hdmi2": "KEY_HDMI2",
    "hdmi 2": "KEY_HDMI2",
}


def _normalize_mac(value: str = "") -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _now_iso() -> str:
    return config.now_local().isoformat()


def _token_file_for(device: TVDevice) -> str:
    stem = (device.device_id or f"samsung-{device.host}").replace(":", "_")
    return str((_TOKEN_DIR / f"{stem}.token").resolve())


def _read_token(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _send_magic_packet(mac: str):
    norm = _normalize_mac(mac)
    if len(norm) != 12:
        raise TVOfflineError("no tengo MAC válida para encender el TV")
    payload = bytes.fromhex("FF" * 6 + norm * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, ("255.255.255.255", 9))


def _extract_device_info(payload: dict) -> dict:
    device = payload.get("device") if isinstance(payload.get("device"), dict) else payload
    if not isinstance(device, dict):
        device = {}
    return {
        "name": str(device.get("name") or device.get("friendlyName") or payload.get("name") or "").strip(),
        "model": str(device.get("modelName") or device.get("model") or payload.get("model") or "").strip(),
        "mac": _normalize_mac(device.get("wifiMac") or device.get("networkMac") or payload.get("wifiMac") or ""),
        "duid": str(device.get("duid") or payload.get("duid") or "").strip(),
        "manufacturer": str(device.get("manufacturer") or device.get("manufacturerName") or payload.get("manufacturer") or "").strip(),
        "raw": device,
    }


def _fetch_device_info(host: str) -> dict:
    try:
        response = requests.get(
            f"http://{host}:8001/api/v2/",
            timeout=_CONNECT_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout as exc:
        raise TVTimeoutError(f"timeout consultando {host}") from exc
    except requests.RequestException as exc:
        raise TVOfflineError(f"no pude contactar al TV en {host}") from exc


def _looks_like_samsung(payload: dict) -> bool:
    info = _extract_device_info(payload)
    text = " ".join([info.get("manufacturer", ""), info.get("model", ""), info.get("name", "")]).lower()
    return "samsung" in text or "tizen" in text or "un50" in text


def _ssdp_discover_hosts(timeout_s: float) -> set[str]:
    hosts: set[str] = set()
    socket_timeout = max(0.5, float(timeout_s))
    for st in _SSDP_TARGETS:
        message = "\r\n".join(
            [
                "M-SEARCH * HTTP/1.1",
                "HOST: 239.255.255.250:1900",
                'MAN: "ssdp:discover"',
                "MX: 1",
                f"ST: {st}",
                "",
                "",
            ]
        ).encode("utf-8")
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(socket_timeout)
            try:
                sock.sendto(message, ("239.255.255.250", 1900))
            except OSError:
                continue
            while True:
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    break
                except OSError:
                    break
                hosts.add(addr[0])
                text = data.decode("utf-8", errors="ignore")
                for line in text.splitlines():
                    if line.lower().startswith("location:"):
                        location = line.split(":", 1)[1].strip()
                        parsed = urlparse(location)
                        if parsed.hostname:
                            hosts.add(parsed.hostname)
    return hosts


def _local_ipv4_candidates() -> set[str]:
    hosts: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                hosts.add(ip)
    except OSError:
        pass
    try:
        for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = sockaddr[0]
            if ip and not ip.startswith("127."):
                hosts.add(ip)
    except OSError:
        pass
    return hosts


def _subnet_prefixes() -> set[ipaddress.IPv4Network]:
    prefixes: set[ipaddress.IPv4Network] = set()
    for host in _local_ipv4_candidates():
        try:
            prefixes.add(ipaddress.ip_network(f"{host}/24", strict=False))
        except ValueError:
            continue
    return prefixes


def _candidate_hosts(timeout_s: float, known: dict[str, TVDevice] | None = None) -> set[str]:
    hosts = set(_DISCOVERY_HOSTS)
    if known:
        for item in known.values():
            if item.host:
                hosts.add(item.host)
    hosts.update(_ssdp_discover_hosts(timeout_s))
    if _SCAN_SUBNET:
        for network in _subnet_prefixes():
            for addr in network.hosts():
                host = str(addr)
                if not host.endswith(".0") and not host.endswith(".255"):
                    hosts.add(host)
    return hosts


def _probe_host(host: str, known: dict[str, TVDevice] | None = None) -> TVDevice | None:
    try:
        return _create_device_from_host(host, known)
    except Exception:
        return None


def _discover_hosts_parallel(hosts: set[str], known: dict[str, TVDevice] | None = None) -> list[TVDevice]:
    devices: list[TVDevice] = []
    seen_keys: set[str] = set()
    with ThreadPoolExecutor(max_workers=32) as executor:
        futures = {executor.submit(_probe_host, host, known): host for host in sorted(hosts)}
        for future in as_completed(futures):
            device = future.result()
            if device is None:
                continue
            key = device.mac or device.host.lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            devices.append(device)
    return devices


def _create_device_from_host(host: str, known: dict[str, TVDevice] | None = None) -> TVDevice | None:
    payload = _fetch_device_info(host)
    if not _looks_like_samsung(payload):
        return None
    info = _extract_device_info(payload)
    existing = None
    if known:
        existing = known.get(info["mac"]) or known.get(host.lower())
    device = TVDevice(
        device_id=(existing.device_id if existing else f"samsung:{info['mac'] or host.lower()}"),
        brand="samsung",
        name=existing.name if existing and existing.name else (info["name"] or f"samsung-{host.split('.')[-1]}"),
        host=host,
        model=info["model"],
        mac=info["mac"],
        token=existing.token if existing else "",
        token_file=existing.token_file if existing and existing.token_file else "",
        connected=True,
        auth_required=False,
        first_seen=existing.first_seen if existing and existing.first_seen else _now_iso(),
        last_seen=_now_iso(),
        last_error="",
        metadata={
            "duid": info["duid"],
            "manufacturer": info["manufacturer"],
        },
    )
    if not device.token_file:
        device.token_file = _token_file_for(device)
    if not device.token:
        device.token = _read_token(device.token_file)
    return device


class SamsungTVController(TVController):
    brand = "samsung"

    @classmethod
    async def discover_host(cls, host: str) -> TVDevice | None:
        if _IMPORT_ERROR:
            return None
        from . import registry

        known = {}
        for item in registry.list_devices():
            if item.brand != cls.brand:
                continue
            if item.mac:
                known[_normalize_mac(item.mac)] = item
            if item.host:
                known[item.host.lower()] = item
        return await asyncio.to_thread(_probe_host, host, known)

    @classmethod
    async def discover(cls, timeout_s: float = _DISCOVERY_TIMEOUT) -> list[TVDevice]:
        if _IMPORT_ERROR:
            return []
        from . import registry

        known = {}
        for item in registry.list_devices():
            if item.brand != cls.brand:
                continue
            if item.mac:
                known[_normalize_mac(item.mac)] = item
            if item.host:
                known[item.host.lower()] = item
        hosts = await asyncio.to_thread(_candidate_hosts, timeout_s, known)
        return await asyncio.to_thread(_discover_hosts_parallel, hosts, known)

    def _client(self, port: int | None = None):
        if SamsungTVWS is None:
            raise RuntimeError(f"samsungtvws no está disponible ({_IMPORT_ERROR})")
        token = self.device.token or _read_token(self.device.token_file)
        return SamsungTVWS(
            host=self.device.host,
            port=int(port or self.device.metadata.get("ws_port") or _WS_PORTS[0]),
            token=token or None,
            token_file=self.device.token_file or None,
            timeout=_CONNECT_TIMEOUT,
            key_press_delay=0.3,
            name=_REMOTE_NAME,
        )

    async def _run_client(self, fn, *args, **kwargs):
        last_exc = None
        ports = [self.device.metadata.get("ws_port")] if self.device.metadata.get("ws_port") else []
        ports.extend(port for port in _WS_PORTS if port not in ports)
        for port in ports:
            client = self._client(port=int(port))
            try:
                result = await asyncio.to_thread(fn, client, *args, **kwargs)
                self.device.metadata["ws_port"] = int(port)
                return result
            except requests.Timeout as exc:
                last_exc = TVTimeoutError("timeout hablando con el TV")
            except Exception as exc:
                message = str(exc).lower()
                if "unauthorized" in message or "denied" in message or "access denied" in message:
                    raise TVUnauthorizedError(str(exc)) from exc
                if "timeout" in message:
                    last_exc = TVTimeoutError(str(exc))
                elif "connection" in message or "refused" in message or "unreachable" in message:
                    last_exc = TVOfflineError(str(exc))
                else:
                    last_exc = exc
                    break
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    with contextlib.suppress(Exception):
                        close()
        if last_exc:
            raise last_exc
        raise TVOfflineError("no pude abrir websocket con el TV")

    async def _send_key(self, key: str, times: int = 1):
        return await self._run_client(lambda client: client.send_key(key, times=times))

    async def connect(self):
        if SamsungTVWS is None:
            return error_result(f"samsungtvws no está disponible ({_IMPORT_ERROR})")
        try:
            payload = await asyncio.to_thread(_fetch_device_info, self.device.host)
            info = _extract_device_info(payload)
            self.device.connected = True
            self.device.last_seen = _now_iso()
            self.device.model = self.device.model or info["model"]
            self.device.mac = self.device.mac or info["mac"]
            self.device.metadata.update({"duid": info["duid"], "manufacturer": info["manufacturer"]})
            self.device.token_file = self.device.token_file or _token_file_for(self.device)
            await self._run_client(lambda client: client.app_list())
            self.device.token = _read_token(self.device.token_file)
            self.device.auth_required = False
            self.device.last_error = ""
            return ok_result("tv samsung conectado", device=self.device.to_dict())
        except TVUnauthorizedError as exc:
            self.device.connected = True
            self.device.auth_required = True
            self.device.last_error = str(exc)
            return error_result("el TV pidió autorización o rechazó el token", device=self.device.to_dict())
        except (TVOfflineError, TVTimeoutError) as exc:
            self.device.connected = False
            self.device.last_error = str(exc)
            return error_result(str(exc), device=self.device.to_dict())
        except Exception as exc:
            self.device.connected = False
            self.device.last_error = str(exc)
            return error_result(f"falló la conexión Samsung: {exc}", device=self.device.to_dict())

    async def power_on(self):
        try:
            await asyncio.to_thread(_send_magic_packet, self.device.mac)
            return ok_result("paquete Wake-on-LAN enviado", device=self.device.to_dict())
        except Exception as exc:
            return error_result(str(exc), device=self.device.to_dict())

    async def power_off(self):
        try:
            await self._send_key("KEY_POWEROFF")
            return ok_result("apagado solicitado", device=self.device.to_dict())
        except Exception as exc:
            return error_result(str(exc), device=self.device.to_dict())

    async def volume_up(self):
        try:
            await self._send_key("KEY_VOLUP")
            self.device.metadata["last_known_volume"] = min(100, int(self.device.metadata.get("last_known_volume", 0)) + 1)
            return ok_result("volumen arriba", device=self.device.to_dict())
        except Exception as exc:
            return error_result(str(exc), device=self.device.to_dict())

    async def volume_down(self):
        try:
            await self._send_key("KEY_VOLDOWN")
            current = int(self.device.metadata.get("last_known_volume", 0))
            self.device.metadata["last_known_volume"] = max(0, current - 1)
            return ok_result("volumen abajo", device=self.device.to_dict())
        except Exception as exc:
            return error_result(str(exc), device=self.device.to_dict())

    async def set_volume(self, level: int):
        target = max(0, min(100, int(level)))
        current = self.device.metadata.get("last_known_volume")
        if current is None:
            return error_result("no conozco el volumen actual del TV; usá subir/bajar primero", device=self.device.to_dict())
        delta = target - int(current)
        if delta == 0:
            return ok_result("el volumen ya estaba en ese nivel", device=self.device.to_dict())
        key = "KEY_VOLUP" if delta > 0 else "KEY_VOLDOWN"
        try:
            await self._send_key(key, times=abs(delta))
            self.device.metadata["last_known_volume"] = target
            return ok_result("volumen ajustado", level=target, device=self.device.to_dict())
        except Exception as exc:
            return error_result(str(exc), device=self.device.to_dict())

    async def mute(self):
        try:
            await self._send_key("KEY_MUTE")
            self.device.metadata["muted"] = not bool(self.device.metadata.get("muted"))
            return ok_result("mute enviado", device=self.device.to_dict())
        except Exception as exc:
            return error_result(str(exc), device=self.device.to_dict())

    async def unmute(self):
        try:
            if self.device.metadata.get("muted") is False:
                return ok_result("el TV ya figuraba sin mute", device=self.device.to_dict())
            await self._send_key("KEY_MUTE")
            self.device.metadata["muted"] = False
            return ok_result("unmute enviado", device=self.device.to_dict())
        except Exception as exc:
            return error_result(str(exc), device=self.device.to_dict())

    async def launch_app(self, app_name: str):
        app_key = str(app_name or "").strip().lower()
        app_ids = _APP_ALIASES.get(app_key)
        if not app_ids:
            return error_result(f"no conozco esa app Samsung: {app_name}", device=self.device.to_dict())
        for app_id in app_ids:
            try:
                await self._run_client(lambda client, value=app_id: client.run_app(value))
                return ok_result("app lanzada", app=app_key, app_id=app_id, device=self.device.to_dict())
            except Exception:
                continue
        return error_result(f"no pude abrir {app_name} en el TV Samsung", device=self.device.to_dict())

    async def send_key(self, key: str):
        raw = str(key or "").strip()
        resolved = _KEY_ALIASES.get(raw.lower(), raw.upper())
        if not resolved.startswith("KEY_"):
            resolved = f"KEY_{resolved}"
        try:
            await self._send_key(resolved)
            return ok_result("tecla enviada", key=resolved, device=self.device.to_dict())
        except Exception as exc:
            return error_result(str(exc), key=resolved, device=self.device.to_dict())

    async def get_status(self):
        try:
            payload = await asyncio.to_thread(_fetch_device_info, self.device.host)
            info = _extract_device_info(payload)
            self.device.connected = True
            self.device.last_seen = _now_iso()
            self.device.model = info["model"] or self.device.model
            self.device.mac = info["mac"] or self.device.mac
            self.device.metadata.update(
                {
                    "duid": info["duid"],
                    "manufacturer": info["manufacturer"],
                    "raw_device": info["raw"],
                }
            )
            return ok_result(
                "tv online",
                online=True,
                device=self.device.to_dict(),
            )
        except Exception as exc:
            self.device.connected = False
            self.device.last_error = str(exc)
            return error_result(str(exc), online=False, device=self.device.to_dict())
