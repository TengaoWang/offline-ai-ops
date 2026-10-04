"""白名单命令执行器（FR-9、FR-3）。

一条命令要过 4 关：① 危险字符 → ② 拆分参数 → ③ 白名单校验 → ④ 不经过 shell 执行（带超时）。
本机命令（ping、ipconfig 等）在 Windows 上真实执行；交换机命令（display、dir）读取技能目录里的回放文件。

    from engine.executor import check, execute
    check("ping 1.1.1.1; rm -rf /")   # → (False, "包含危险字符「;」")
    execute("ping -n 2 -w 1000 192.168.10.1")
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import yaml
from .simulator import SimulatorClient, SimulatorError

WHITELIST_PATH = Path(__file__).with_name("whitelist.yaml")
REJECTED_TEXT = "该命令不在白名单，已拒绝"
OUTPUT_LIMIT = 8 * 1024
DEFAULT_TIMEOUT = 10

_HOST = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252}))$")
_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/:._-]*$")

_whitelist: dict | None = None


def whitelist() -> dict:
    global _whitelist
    if _whitelist is None:
        _whitelist = yaml.safe_load(WHITELIST_PATH.read_text(encoding="utf-8"))
    return _whitelist


def _check_args(name: str, args: list[str], rule: dict) -> str | None:
    """按白名单规则检查参数；通过返回 None，否则返回原因。"""
    flags = rule.get("flags") or {}
    allowed = rule.get("args")
    positional = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in flags:
            spec = flags[arg]
            if spec is not None:  # 后面要跟一个整数
                if i + 1 >= len(args) or not args[i + 1].isdigit():
                    return f"{arg} 后面需要一个数字"
                if int(args[i + 1]) > spec["max"]:
                    return f"{arg} 的值不能超过 {spec['max']}"
                i += 1
        elif arg.startswith("-"):
            return f"不允许的参数「{arg}」"
        else:
            positional.append(arg)
        i += 1
    if len(positional) > rule.get("max_args", 0):
        return "参数过多"
    for arg in positional:
        if allowed == "host":
            if not _HOST.match(arg):
                return f"「{arg}」不是合法的 IP 或主机名"
        elif allowed == "word":
            if not _WORD.match(arg):
                return f"不允许的参数「{arg}」"
        elif isinstance(allowed, list):
            if arg.lower() not in allowed:
                return f"不允许的参数「{arg}」"
        else:
            return f"{name} 不接受参数「{arg}」"
    return None


def check(command: str, target: str = "local") -> tuple[bool, str]:
    """校验一条命令能否执行。target：local（本机 Windows）/ local_mac（本机 macOS）/ switch（交换机）。
    返回 (是否放行, 原因)。"""
    rules = whitelist()
    for char in rules["dangerous_chars"]:
        if char in command:
            shown = {"\n": "换行", "\r": "换行"}.get(char, char)
            return False, f"包含危险字符「{shown}」"
    try:
        args = shlex.split(command)
    except ValueError as exc:
        return False, f"无法解析：{exc}"
    if not args:
        return False, "空命令"
    name = args[0].lower()
    if name in rules["denied"]:
        return False, f"「{args[0]}」是禁止执行的命令"
    table = rules.get(target) or {}
    if name not in table:
        return False, f"「{args[0]}」不在白名单"
    reason = _check_args(name, args[1:], table[name])
    if reason:
        return False, reason
    return True, "ok"


def _decode(data: bytes) -> str:
    """中文 Windows 的命令输出是 GBK：先试 UTF-8，失败再用 GBK。"""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def _subprocess_runner(args: list[str], timeout: float) -> tuple[int, bytes]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(args, shell=False, capture_output=True, timeout=timeout, creationflags=flags)
    return result.returncode, result.stdout + result.stderr


Runner = Callable[[list[str], float], tuple[int, bytes]]


PLATFORM_TARGET = {"win32": "local", "darwin": "local_mac"}  # 本机命令按哪个平台的写法执行


def local_target() -> str | None:
    """当前系统对应的本机命令类型：Windows → local，macOS → local_mac，其他 → None。"""
    return PLATFORM_TARGET.get(sys.platform)


def live_supported(target: str | None = None) -> bool:
    """这类命令在当前系统上是否真实执行（不传 target 时：本机命令是否真实执行）。

    Windows 上执行 Windows 写法（local），macOS 上执行 macOS 写法（local_mac），交换机命令一律回放。
    ENGINE_MODE=replay 强制全部回放（演示备用），ENGINE_MODE=live 强制真实执行。"""
    mode = os.environ.get("ENGINE_MODE", "auto").lower()
    if mode == "replay" or target == "switch":
        return False
    if mode == "live":
        return True
    return local_target() is not None and (target is None or target == local_target())


def read_replay(path: Path) -> tuple[str, str, str]:
    """读取回放文件，返回 (正文, 来源说明, 状态)。

    文件开头以 `# ` 开头的行是说明：`# 来源：…` 写出处，`# status: failed` 指定执行状态（默认 success）。"""
    notes, body, status = [], [], "success"
    lines = path.read_text(encoding="utf-8").splitlines()
    header = True
    for line in lines:
        if header and line.startswith("# "):
            note = line[2:].strip()
            if note.lower().startswith("status:"):
                status = note.split(":", 1)[1].strip()
            else:
                notes.append(note)
            continue
        header = False
        body.append(line)
    return "\n".join(body).strip("\n"), "；".join(notes), status


def execute(command: str, target: str = "local", timeout: float = DEFAULT_TIMEOUT,
            replay: Path | None = None, runner: Runner | None = None, force_replay: bool = False) -> dict:
    """执行一条命令，返回 {cmd, status, duration, output, raw, mode, replay_source}。

    status：success / failed / timeout / rejected。
    output：界面显示的内容（回放会在第一行标明「模拟回放」和来源）；raw：命令的原始输出，规则判定用它。
    mode：live（真实执行）/ replay（读回放文件）/ rejected。
    force_replay：这一次全部读回放（界面的「模拟」模式），不受 ENGINE_MODE 影响。"""
    started = time.monotonic()
    ok, reason = check(command, target)
    if not ok:
        return {"cmd": command, "status": "rejected", "duration": 0.0,
                "output": f"{REJECTED_TEXT}（{reason}）", "raw": "", "mode": "rejected", "replay_source": None}

    if force_replay or not live_supported(target):
        if replay is None or not replay.exists():
            return {"cmd": command, "status": "failed", "duration": 0.0,
                    "output": "没有可用的回放数据（未连接真实设备）", "raw": "", "mode": "replay", "replay_source": None}
        raw, source, status = read_replay(replay)
        label = "【模拟回放" + (f" · {source}" if source else "") + "】"
        return {"cmd": command, "status": status, "duration": round(time.monotonic() - started, 2),
                "output": f"{label}\n{raw}", "raw": raw, "mode": "replay", "replay_source": source}

    run = runner or _subprocess_runner
    try:
        code, data = run(shlex.split(command), timeout)
        raw = _decode(data)
        status = "success" if code == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        raw = _decode(exc.output or b"")
        status = "timeout"
    except OSError as exc:
        raw = f"无法执行：{exc}"
        status = "failed"
    raw = raw.replace("\r\n", "\n").strip()
    if len(raw.encode("utf-8")) > OUTPUT_LIMIT:
        raw = raw.encode("utf-8")[:OUTPUT_LIMIT].decode("utf-8", errors="ignore") + "\n…（输出过长，已截断）"
    output = raw if status != "timeout" else (raw + f"\n（超过 {timeout:g} 秒，已停止）").strip()
    return {"cmd": command, "status": status, "duration": round(time.monotonic() - started, 2),
            "output": output or "（无输出）", "raw": raw, "mode": "live", "replay_source": None}


def execute_simulator(command: str, device: str | None, client: SimulatorClient,
                      action: str = "command") -> dict:
    """Execute one validated read-only operation through the loopback simulator API."""
    started = time.monotonic()
    mapping = {"action": action}
    if action == "command":
        mapping.update(device=device, command=command)
    try:
        response = client.execute(mapping)
        raw = response["output"].replace("\r\n", "\n").strip()
        if len(raw.encode("utf-8")) > OUTPUT_LIMIT:
            raw = raw.encode("utf-8")[:OUTPUT_LIMIT].decode("utf-8", errors="ignore") + "\n…（输出过长，已截断）"
        status = "success" if response["ok"] else "failed"
        display = f"{response['device']}> {response['command']}" if response["device"] else f"simulator:{action}"
        return {"cmd": display, "status": status, "duration": round(time.monotonic() - started, 2),
                "output": raw or "（无输出）", "raw": raw, "mode": "simulator", "replay_source": None,
                "simulator": {"epoch": client.epoch, "device": response["device"],
                              "revision": response["revision"], "mutation": False}}
    except SimulatorError as exc:
        return {"cmd": f"{device}> {command}" if device else f"simulator:{action}", "status": "failed",
                "duration": round(time.monotonic() - started, 2), "output": str(exc), "raw": "",
                "mode": "simulator", "replay_source": None,
                "simulator": {"epoch": client.epoch, "device": device, "revision": None, "mutation": False,
                              "error_code": exc.code}}
