"""Allowlisted read-only command execution. Commands are never passed to a shell."""
from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Callable


class CommandRejected(ValueError):
    pass


FORBIDDEN = re.compile(r"[;|&`<>\r\n]|\$\(")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:%_-]{0,252}$")
SERVICE = re.compile(r"^[A-Za-z0-9@_.:-]{1,128}$")
MAX_OUTPUT_BYTES = 64 * 1024
DEFAULT_TIMEOUT_S = 10.0
MAX_TIMEOUT_S = 30.0
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def _small_int(value: str, maximum: int) -> bool:
    return value.isdigit() and 0 < int(value) <= maximum


def _safe_log_path(value: str) -> bool:
    path = Path(value)
    return path.is_absolute() and ".." not in path.parts and path.parts[:2] == ("/", "var") and len(path.parts) >= 3 and path.parts[2] == "log"


def _policy(program: str, args: list[str]) -> bool:
    if program == "df":
        return args in (["-P"], ["-h"])
    if program == "ping":
        return (len(args) == 3 and args[0] in {"-c", "-n"} and _small_int(args[1], 4)
                and bool(HOST.fullmatch(args[2])) and not args[2].startswith("-"))
    if program == "netstat":
        return args in (["-rn"], ["-an"])
    if program == "ps":
        return args in (["-axo", "pid,comm"], ["aux"])
    if program in {"uptime", "who"}:
        return not args
    if program == "last":
        return len(args) == 2 and args[0] == "-n" and _small_int(args[1], 20)
    if program == "uname":
        return args in (["-a"], ["-n"])
    if program == "ss":
        return args in (["-ltn"], ["-ltnp"])
    if program == "systemctl":
        return len(args) == 2 and args[0] in {"status", "show", "is-active"} and bool(SERVICE.fullmatch(args[1]))
    if program == "journalctl":
        return (len(args) == 5 and args[0] == "-u" and bool(SERVICE.fullmatch(args[1]))
                and args[2] == "-n" and _small_int(args[3], 200) and args[4] == "--no-pager")
    if program == "tail":
        return len(args) == 3 and args[0] == "-n" and _small_int(args[1], 200) and _safe_log_path(args[2])
    if program == "du":
        return len(args) == 2 and args[0] in {"-sk", "-sh"} and args[1] in {"/tmp", "/var/log"}
    return False


def validate_argv(argv) -> list[str]:
    if not isinstance(argv, list) or not 1 <= len(argv) <= 32 or not all(isinstance(x, str) for x in argv):
        raise CommandRejected("命令必须是 1～32 项字符串参数数组")
    if any(not value or len(value) > 512 or FORBIDDEN.search(value) for value in argv):
        raise CommandRejected("命令包含空参数、超长参数或 shell 注入字符")
    program = argv[0]
    if Path(program).name != program or not _policy(program, argv[1:]):
        raise CommandRejected(f"命令不在只读白名单：{shlex.join(argv)}")
    return list(argv)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _bounded(data: bytes) -> tuple[str, bool]:
    truncated = len(data) > MAX_OUTPUT_BYTES
    value = data[:MAX_OUTPUT_BYTES]
    text = _decode(value)
    if truncated:
        text += "\n[输出已截断：超过 64 KiB]"
    return text, truncated


def parse_output(name: str, output: str, returncode: int) -> dict:
    if name == "ping":
        loss = re.search(r"(\d+(?:\.\d+)?)%\s*(?:packet )?loss", output, re.I)
        success_rate = re.search(r"Success rate is\s+(\d+)\s+percent", output, re.I)
        loss_pct = float(loss.group(1)) if loss else (100.0 - float(success_rate.group(1)) if success_rate else (0.0 if returncode == 0 else 100.0))
        return {"loss_pct": loss_pct, "reachable": returncode == 0 and loss_pct < 100}
    if name == "df_posix":
        candidates = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and parts[-2].endswith("%") and parts[-2][:-1].isdigit():
                candidates.append((int(parts[-2][:-1]), parts[-1]))
        usage, mount = max(candidates, default=(0, ""))
        return {"max_usage_pct": usage, "fullest_mount": mount, "filesystems": len(candidates)}
    if name == "line_count":
        lines = [line for line in output.splitlines() if line.strip()]
        return {"line_count": max(0, len(lines) - 1)}
    if name == "session_count":
        return {"session_count": len([line for line in output.splitlines() if line.strip()])}
    return {"returncode": returncode, "has_output": bool(output.strip())}


class Executor:
    def __init__(self, runtime_dir: Path | str):
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def execute_one(self, command: dict, mode: str) -> dict:
        argv = validate_argv(command.get("argv"))
        timeout = float(command.get("timeout_s", DEFAULT_TIMEOUT_S))
        if not 0 < timeout <= MAX_TIMEOUT_S:
            raise CommandRejected("命令超时必须大于 0 且不超过 30 秒")
        started = time.perf_counter()
        if mode == "simulation":
            fixture = command.get("simulation") or {}
            status = fixture.get("status", "success")
            if status not in {"success", "failed", "timeout"}:
                raise CommandRejected("simulation.status 非法")
            output, truncated = _bounded(str(fixture.get("output", "")).encode("utf-8"))
            returncode = int(fixture.get("returncode", 0 if status == "success" else 1))
            duration = float(fixture.get("duration_s", 0.01))
            parsed = parse_output(command.get("parser", "generic"), output, returncode)
            return {"command_id": command["id"], "argv": argv, "display": shlex.join(argv),
                    "cmd": shlex.join(argv), "output": output, "status": status,
                    "returncode": returncode, "duration_s": duration, "duration": duration,
                    "required": bool(command.get("required", True)), "truncated": truncated, "parsed": parsed}
        if mode != "real":
            raise CommandRejected("执行模式只允许 real 或 simulation")
        env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        try:
            result = subprocess.run(argv, shell=False, cwd=self.runtime_dir, env=env, capture_output=True,
                                    timeout=timeout, check=False)
            combined = result.stdout + ((b"\n" if result.stdout and result.stderr else b"") + result.stderr)
            output, truncated = _bounded(combined)
            status = "success" if result.returncode == 0 else "failed"
            returncode = result.returncode
        except subprocess.TimeoutExpired as exc:
            combined = (exc.stdout or b"") + (exc.stderr or b"")
            output, truncated = _bounded(combined)
            output = (output + "\n[命令执行超时]").strip()
            status, returncode = "timeout", None
        except OSError as exc:
            output, truncated, status, returncode = str(exc), False, "failed", None
        duration = round(time.perf_counter() - started, 3)
        parsed = parse_output(command.get("parser", "generic"), output, returncode if returncode is not None else 1)
        return {"command_id": command["id"], "argv": argv, "display": shlex.join(argv),
                "cmd": shlex.join(argv), "output": output, "status": status,
                "returncode": returncode, "duration_s": duration, "duration": duration,
                "required": bool(command.get("required", True)), "truncated": truncated, "parsed": parsed}

    def execute(self, commands: list[dict], mode: str, emit: Callable[[str, dict], None] | None = None) -> list[dict]:
        results = []
        for index, command in enumerate(commands, 1):
            try:
                item = self.execute_one(command, mode)
            except CommandRejected as exc:
                item = {"command_id": str(command.get("id", "unknown")), "argv": command.get("argv"),
                        "display": "", "cmd": "", "output": str(exc), "status": "rejected",
                        "returncode": None, "duration_s": 0.0, "duration": 0.0,
                        "required": bool(command.get("required", True)), "truncated": False, "parsed": {}}
            results.append(item)
            if emit:
                emit("collect", {"index": index, **item})
            if item["required"] and item["status"] != "success":
                break
        return results
