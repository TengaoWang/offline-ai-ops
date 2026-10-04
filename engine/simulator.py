"""Loopback-only client for the switch lab assistant API."""
from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_SIMULATOR_URL = "http://127.0.0.1:8878/api/v1"
MAX_RESPONSE_BYTES = 1024 * 1024
DEVICE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
READ_ONLY_COMMANDS = (
    re.compile(r"^display (?:version|interface brief|interface [A-Za-z0-9/ -]+|port vlan(?: [A-Za-z0-9/ -]+)?|"
               r"ip interface brief|ip routing-table(?: \d{1,3}(?:\.\d{1,3}){3})?|arp all|"
               r"current-configuration(?: interface [A-Za-z0-9/ -]+)?|this|logbuffer)$", re.I),
    re.compile(r"^ping(?: -c 3)? \d{1,3}(?:\.\d{1,3}){3}$", re.I),
    re.compile(r"^(?:ipconfig|help|\?)$", re.I),
)


class SimulatorError(RuntimeError):
    def __init__(self, message: str, code: str = "simulator_error", status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status


def normalize_simulator_target(target: dict | None) -> dict:
    if not isinstance(target, dict):
        raise SimulatorError("模拟器目标必须是对象", "invalid_target", 400)
    raw_url = target.get("base_url") or DEFAULT_SIMULATOR_URL
    if not isinstance(raw_url, str) or len(raw_url) > 300:
        raise SimulatorError("模拟器地址无效", "invalid_target", 400)
    parsed = urllib.parse.urlsplit(raw_url.rstrip("/"))
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SimulatorError("模拟器只允许使用本机 HTTP 回环地址", "invalid_target", 400)
    try:
        loopback = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        port = parsed.port
    except ValueError as exc:
        raise SimulatorError("模拟器地址无效", "invalid_target", 400) from exc
    if not loopback or not port or parsed.path.rstrip("/") != "/api/v1":
        raise SimulatorError("模拟器地址必须是本机回环地址的 /api/v1", "invalid_target", 400)
    display_name = target.get("display_name") or "switch-lab"
    if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 100:
        raise SimulatorError("模拟器显示名称无效", "invalid_target", 400)
    host = f"[{parsed.hostname}]" if ":" in (parsed.hostname or "") else parsed.hostname
    return {"kind": "simulator", "display_name": display_name.strip(),
            "base_url": f"http://{host}:{port}/api/v1"}


def validate_simulator_mapping(mapping: Any) -> dict:
    if not isinstance(mapping, dict):
        raise SimulatorError("模拟器命令缺少 simulator 映射", "invalid_skill", 400)
    action = mapping.get("action", "command")
    if action not in {"command", "probe", "observation", "logs", "diagnose", "repair", "repair-route", "repair-arp"}:
        raise SimulatorError("simulator.action 非法", "invalid_skill", 400)
    normalized = {"action": action}
    if action == "command":
        device, command = mapping.get("device"), mapping.get("command")
        if not isinstance(device, str) or not DEVICE.fullmatch(device):
            raise SimulatorError("模拟器设备名无效", "invalid_skill", 400)
        if not isinstance(command, str) or not 1 <= len(command) <= 500 or "\n" in command or "\r" in command:
            raise SimulatorError("模拟器命令必须是单行文本", "invalid_skill", 400)
        command = " ".join(command.split())
        if not any(pattern.fullmatch(command) for pattern in READ_ONLY_COMMANDS):
            raise SimulatorError(f"模拟器命令不在只读白名单：{command}", "invalid_skill", 400)
        normalized.update(device=device, command=command)
    return normalized


class SimulatorClient:
    def __init__(self, target: dict, session: str, timeout: float = 5.0):
        self.target = normalize_simulator_target(target)
        self.base_url = self.target["base_url"]
        self.session = session[:100]
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.health_data: dict = {}
        self.observation: dict = {}
        self.epoch = ""
        self.devices: set[str] = set()
        self.contexts: set[str] = set()

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8"} if data is not None else {},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise SimulatorError("模拟器响应超过 1 MiB", "simulator_protocol_error")
        except urllib.error.HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES)
            try:
                detail = json.loads(raw.decode("utf-8")).get("error")
            except (ValueError, UnicodeDecodeError, AttributeError):
                detail = None
            status = 409 if exc.code == 409 else 502
            raise SimulatorError(detail or f"模拟器返回 HTTP {exc.code}", "simulator_stale" if exc.code == 409 else "simulator_http_error", status) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SimulatorError(f"无法连接交换机模拟器：{exc}", "simulator_unavailable", 503) from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SimulatorError("模拟器返回了无效 JSON", "simulator_protocol_error") from exc
        if not isinstance(result, dict):
            raise SimulatorError("模拟器响应必须是 JSON 对象", "simulator_protocol_error")
        return result

    def prepare(self) -> dict:
        health = self._request("GET", "/health")
        if health.get("status") != "ready" or health.get("service") != "fieldnote-switch-simulator":
            raise SimulatorError("目标不是已就绪的交换机模拟器", "simulator_not_ready", 503)
        observation = self._request("GET", "/observation")
        epoch = observation.get("epoch")
        if not isinstance(epoch, str) or not epoch or epoch != health.get("epoch"):
            raise SimulatorError("模拟器实验编号不一致", "simulator_protocol_error")
        devices = observation.get("devices")
        if not isinstance(devices, list) or not all(isinstance(item, str) for item in devices):
            raise SimulatorError("模拟器设备列表无效", "simulator_protocol_error")
        self.health_data, self.observation = health, observation
        self.epoch, self.devices = epoch, set(devices)
        return observation

    def _ensure_context(self, device: str) -> None:
        if device in self.contexts:
            return
        if device not in self.devices:
            raise SimulatorError(f"模拟器不存在设备：{device}", "simulator_device_unknown", 400)
        response = self._request("POST", "/context", {"session": self.session, "device": device})
        if response.get("epoch") != self.epoch:
            raise SimulatorError("建立设备会话时实验编号发生变化", "simulator_stale", 409)
        self.contexts.add(device)

    def execute(self, mapping: dict) -> dict:
        mapping = validate_simulator_mapping(mapping)
        action = mapping["action"]
        if action == "command":
            device, command = mapping["device"], mapping["command"]
            self._ensure_context(device)
            payload = self._request("POST", "/command", {
                "session": self.session, "device": device, "epoch": self.epoch, "command": command,
            })
            records = payload.get("records")
            if not isinstance(records, list) or not records:
                raise SimulatorError("模拟器命令响应缺少 records", "simulator_protocol_error")
            if any(record.get("mutation") for record in records if isinstance(record, dict)):
                raise SimulatorError("模拟器把只读采集标记为配置修改，已停止", "simulator_protocol_error")
            ok = all(isinstance(record, dict) and record.get("ok") is True for record in records)
            output = "\n".join(str(record.get("output", "")) for record in records if isinstance(record, dict))
            return {"action": action, "device": device, "command": command, "ok": ok,
                    "output": output, "raw": payload, "revision": payload.get("observation", {}).get("revision")}
        if action == "probe":
            payload = self._request("POST", "/probe", {"epoch": self.epoch})
        elif action == "diagnose":
            payload = self._request("POST", "/diagnose", {"epoch": self.epoch})
        elif action in {"repair", "repair-route", "repair-arp"}:
            expected = {"repair-route": "C", "repair-arp": "D"}.get(action)
            request = {"epoch": self.epoch, "session": self.session}
            if expected:
                request["expected"] = expected
            payload = self._request("POST", "/repair", request)
        elif action == "logs":
            payload = self._request("GET", "/logs")
        else:
            payload = self._request("GET", "/observation")
        revision = (payload.get("revision") or payload.get("probe", {}).get("revision")
                    or payload.get("diagnosis", {}).get("revision") or payload.get("repair", {}).get("revision"))
        return {"action": action, "device": None, "command": action, "ok": True,
                "output": json.dumps(payload, ensure_ascii=False), "raw": payload,
                "revision": revision}
