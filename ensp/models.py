"""Configuration and JSON contracts for the local eNSP console adapter."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


class EnspError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def interface_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("interface must be a string")
    match = re.fullmatch(r"(?:GigabitEthernet|GE)(\d{1,2}/\d{1,2}/\d{1,3})", value, re.I)
    if not match:
        raise ValueError("interface must look like GigabitEthernet0/0/1")
    return "GigabitEthernet" + match[1]


def ipv4(value: str) -> str:
    address = ipaddress.IPv4Address(value)
    if address.is_multicast or address.is_unspecified or address.is_loopback or int(address) == 0xFFFFFFFF:
        raise ValueError("probe address must be a unicast business IPv4 address")
    return str(address)


@dataclass(frozen=True)
class Endpoint:
    name: str
    port: int
    host: str = "127.0.0.1"

    def __post_init__(self):
        if not isinstance(self.name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", self.name):
            raise ValueError("device name must contain 1-40 ASCII letters, digits, _, . or -")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("console port must be an integer between 1 and 65535")
        if self.host != "127.0.0.1":
            raise ValueError("this demo adapter only connects to local eNSP at 127.0.0.1")


@dataclass(frozen=True)
class LabConfig:
    switch: Endpoint
    probe: Endpoint
    interface: str = "GigabitEthernet0/0/1"
    destination: str = "192.168.10.1"
    source: str = "192.168.10.2"
    expected_enabled: bool = True
    timeout: float = 12.0
    encoding: str = "utf-8"

    def __post_init__(self):
        object.__setattr__(self, "interface", interface_name(self.interface))
        object.__setattr__(self, "destination", ipv4(self.destination))
        object.__setattr__(self, "source", ipv4(self.source))
        if self.destination == self.source:
            raise ValueError("probe source and destination must differ")
        if self.switch.port == self.probe.port or self.switch.name == self.probe.name:
            raise ValueError("switch and probe need distinct console ports and names")
        if type(self.expected_enabled) is not bool:
            raise ValueError("expected_enabled must be a JSON boolean")
        if type(self.timeout) not in (int, float) or not 1 <= self.timeout <= 60:
            raise ValueError("timeout must be between 1 and 60 seconds")
        if self.encoding not in ("utf-8", "gb18030"):
            raise ValueError("encoding must be utf-8 or gb18030")

    @classmethod
    def load(cls, path: str | Path) -> "LabConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("configuration must be a JSON object")
        data = dict(data)
        data["switch"] = Endpoint(**data["switch"])
        data["probe"] = Endpoint(**data["probe"])
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()


@dataclass
class CommandResult:
    device: str
    command: str
    status: str
    raw_output: str
    started_at: str
    duration_ms: int
    error: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)
