from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TVCommandResult:
    ok: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "message": self.message,
            "data": dict(self.data or {}),
        }


@dataclass
class TVDevice:
    device_id: str
    brand: str
    name: str
    host: str
    model: str = ""
    mac: str = ""
    token: str = ""
    token_file: str = ""
    connected: bool = False
    auth_required: bool = False
    first_seen: str = ""
    last_seen: str = ""
    last_error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata or {})
        return payload


def ok_result(message: str = "ok", **data) -> TVCommandResult:
    return TVCommandResult(True, message, dict(data))


def error_result(message: str, **data) -> TVCommandResult:
    return TVCommandResult(False, message, dict(data))


class TVError(RuntimeError):
    pass


class TVNotFoundError(TVError):
    pass


class TVOfflineError(TVError):
    pass


class TVTimeoutError(TVError):
    pass


class TVUnauthorizedError(TVError):
    pass


class TVController(ABC):
    brand = "unknown"

    def __init__(self, device: TVDevice):
        self.device = device

    @classmethod
    @abstractmethod
    async def discover(cls, timeout_s: float = 4.0) -> list[TVDevice]:
        raise NotImplementedError

    @abstractmethod
    async def connect(self) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def power_on(self) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def power_off(self) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def volume_up(self) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def volume_down(self) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def set_volume(self, level: int) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def mute(self) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def unmute(self) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def launch_app(self, app_name: str) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def send_key(self, key: str) -> TVCommandResult:
        raise NotImplementedError

    @abstractmethod
    async def get_status(self) -> TVCommandResult:
        raise NotImplementedError
