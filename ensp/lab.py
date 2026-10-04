"""Explicit write operations for the disposable two-switch DEMO lab, never an HTTP API."""

import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path

from .__main__ import DEFAULT_CONFIG
from .models import EnspError, LabConfig
from .transport import ConsoleSession
from .vrp import is_vrp


def operate(config: LabConfig, action: str, *, session_factory=ConsoleSession):
    if action not in ("prepare", "fault", "restore"):
        raise ValueError("unknown lab action")
    results = []
    endpoints = (config.switch, config.probe) if action == "prepare" else (config.switch,)
    with ExitStack() as stack:
        sessions = {}
        # Check every endpoint before writing anything.
        for endpoint in endpoints:
            session = stack.enter_context(session_factory(endpoint, config.timeout, config.encoding))
            version = session.execute("display version")
            if not is_vrp(version) or "S5700" not in version.upper():
                raise EnspError("unexpected_device", "Lab writes require an eNSP S5700 console.")
            permitted = {f"<{endpoint.name}>"}
            if action == "prepare":
                permitted.update(("<Huawei>", "<HUAWEI>"))
            if session.prompt not in permitted:
                raise EnspError("unexpected_device", f"Console name {session.prompt} is not the intended disposable lab device.")
            sessions[endpoint.name] = session
        for endpoint in endpoints:
            session = sessions[endpoint.name]
            if action == "prepare":
                ip = config.destination if endpoint == config.switch else config.source
                planned = ["system-view", f"sysname {endpoint.name}", "vlan 10", "quit",
                           f"interface {config.interface}", "port link-type access", "port default vlan 10",
                           "undo shutdown", "quit", "interface Vlanif10", f"ip address {ip} 255.255.255.0", "return"]
            else:
                planned = ["system-view", f"interface {config.interface}",
                           "shutdown" if action == "fault" else "undo shutdown", "return"]
            try:
                for command in planned:
                    output = session.execute(command)
                    results.append({"device": endpoint.name, "command": command, "raw_output": output})
            finally:
                if session.sock and session.prompt.startswith("["):
                    session.execute("return")
    return {"lab_only": True, "action": action, "commands": results,
            "note": "Commands completed; run a fresh diagnose/verify to check actual connectivity. Configuration was not saved."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="WRITE commands for the disposable eNSP demo topology only")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--confirm-lab", action="store_true", help="Confirm these console ports belong to the disposable demo topology")
    parser.add_argument("action", choices=("prepare", "fault", "restore"))
    args = parser.parse_args(argv)
    if not args.confirm_lab:
        parser.error("lab writes require --confirm-lab; never point this tool at another topology")
    try:
        config = LabConfig.load(args.config)
        # The supplied lab specifically uses /24 VLAN 10 on a direct link.
        if config.source.rsplit(".", 1)[0] != config.destination.rsplit(".", 1)[0] or any(
            ip.endswith((".0", ".255")) for ip in (config.source, config.destination)
        ):
            raise ValueError("lab preparation requires two host addresses in the same /24")
        print(json.dumps(operate(config, args.action), ensure_ascii=False, indent=2))
        return 0
    except (EnspError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"error": {"code": getattr(exc, "code", "invalid_input"), "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
