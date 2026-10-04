"""Deterministic parsers and the narrow read-only command policy."""

import re

from .models import EnspError, LabConfig


MANUAL_REFERENCE = {
    "document": "华为S系列园区交换机维护宝典",
    "version": "25 (2026-08-31)",
    "section": "8.2.1 人为因素导致接口物理DOWN",
    "pdf_page": 209,
    "printed_page": 131,
    "excerpt": "若current state字段为“Administratively down”，表示接口被人为shutdown，请在接口下执行undo shutdown命令。",
    "source": "curated_manual_reference",
}


def commands(config: LabConfig) -> dict[str, list[str]]:
    return {
        config.switch.name: [
            "display version",
            f"display interface {config.interface}",
            f"display current-configuration interface {config.interface}",
        ],
        config.probe.name: [
            "display version",
            f"ping -c 3 -t 1000 -a {config.source} {config.destination}",
        ],
    }


def require_allowed(config: LabConfig, device: str, command: str) -> None:
    if command not in commands(config).get(device, []):
        raise EnspError("command_denied", "命令不在此设备的精确白名单中，未发送到设备。")


def parse_interface(output: str, expected: str) -> dict:
    match = re.search(r"(?im)^\s*" + re.escape(expected) + r"\s+current state\s*:\s*([^\r\n]+)", output)
    protocol = re.search(r"(?im)^\s*Line protocol current state\s*:\s*([^\r\n]+)", output)
    if not match or not protocol:
        return {"state": "unknown", "physical": None, "protocol": None}
    physical, line = match[1].strip(), protocol[1].strip()
    upper = physical.upper()
    if "ADMINISTRATIVELY" in upper and "DOWN" in upper:
        state = "admin_down"
    elif "ERROR" in upper and "DOWN" in upper:
        state = "error_down"
    elif upper == "UP" and line.upper() == "UP":
        state = "up"
    elif "DOWN" in upper or "DOWN" in line.upper():
        state = "down"
    else:
        state = "unknown"
    return {"state": state, "physical": physical, "protocol": line}


def parse_ping(output: str) -> dict:
    transmitted = re.search(r"(?im)^\s*(\d+)\s+packet\(s\) transmitted", output)
    received = re.search(r"(?im)^\s*(\d+)\s+packet\(s\) received", output)
    loss = re.search(r"(?im)^\s*(\d+(?:\.\d+)?)%\s+packet loss", output)
    if not transmitted or not received or not loss:
        return {"state": "unknown", "sent": None, "received": None, "loss_percent": None}
    sent, replies, percent = int(transmitted[1]), int(received[1]), float(loss[1])
    consistent = sent == 3 and 0 <= replies <= sent and abs(percent - (sent - replies) * 100 / sent) <= 0.1
    if not consistent:
        return {"state": "unknown", "sent": sent, "received": replies, "loss_percent": percent}
    return {"state": "pass" if replies == 3 and percent == 0 else "fail", "sent": sent, "received": replies, "loss_percent": percent}


def is_vrp(output: str) -> bool:
    return bool(re.search(r"Huawei.*Versatile Routing Platform|VRP\s*\(R\).*software|VRP.*Software.*Version", output, re.I))
