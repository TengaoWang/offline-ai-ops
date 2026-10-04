"""Explicitly labelled development fixtures. Never selected by a failed live connection."""

from .models import EnspError, LabConfig

SCENARIOS = ("admin-down", "healthy", "link-down", "error-down", "ping-failed", "unavailable")


def fixture_factory(config: LabConfig, scenario: str):
    if scenario not in SCENARIOS:
        raise ValueError("unknown fixture scenario")

    class FixtureSession:
        def __init__(self, endpoint, timeout=12, encoding="utf-8"):
            self.endpoint = endpoint
            self.last_output = ""

        def __enter__(self):
            if scenario == "unavailable":
                raise EnspError("connection_failed", "[FIXTURE] 模拟控制台未启动。")
            return self

        def close(self):
            pass

        def execute(self, command, on_output=None):
            if command == "display version":
                body = "Huawei Versatile Routing Platform Software\nVRP (R) software, Version 5.110 (S5700 V200R001C00)"
            elif command.startswith("display interface "):
                physical = {"admin-down": "Administratively DOWN", "link-down": "DOWN", "error-down": "ERROR DOWN(link-flap)"}.get(scenario, "UP")
                body = f"{config.interface} current state : {physical}\nLine protocol current state : {'UP' if physical == 'UP' else 'DOWN'}\nDescription: OPS DEMO BUSINESS PORT"
            elif command.startswith("display current-configuration"):
                body = f"#\ninterface {config.interface}\n port link-type access\n port default vlan 10\n" + (" shutdown\n" if scenario == "admin-down" else "") + "#\nreturn"
            elif command.startswith("ping "):
                replies = 3 if scenario == "healthy" else 0
                body = f"PING {config.destination}: 56 data bytes\n--- {config.destination} ping statistics ---\n  3 packet(s) transmitted\n  {replies} packet(s) received\n  {0 if replies else 100}.00% packet loss"
            else:
                raise EnspError("command_denied", "fixture does not implement this command")
            self.last_output = f"{command}\n{body}\n<{self.endpoint.name}>"
            if on_output:
                on_output(self.last_output)
            return self.last_output

    return FixtureSession
