"""Connector contract tests plus a real TCP/Telnet fake; no eNSP/Ollama required."""

import http.client
import json
import socketserver
import threading
import time
import unittest
from contextlib import contextmanager
from dataclasses import replace

from ensp import Endpoint, EnspError, EnspService, LabConfig
from ensp.fixtures import fixture_factory
from ensp.http_api import PREFIX, make_server
from ensp.lab import operate
from ensp.transport import ConsoleSession, TelnetCodec, clean_terminal
from ensp.vrp import parse_interface, parse_ping, require_allowed


def config():
    return LabConfig(Endpoint("OPS-SW1", 2000), Endpoint("OPS-PROBE", 2001))


def fixture(scenario="admin-down", cfg=None):
    cfg = cfg or config()
    return EnspService(cfg, session_factory=fixture_factory(cfg, scenario), mode="fixture")


@contextmanager
def console(handler):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            try:
                handler(self.request)
            except (OSError, AssertionError):
                pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield Endpoint("test", server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def line(sock):
    data = bytearray()
    while not data.endswith(b"\n"):
        part = sock.recv(1)
        if not part:
            return bytes(data)
        data.extend(part)
    return bytes(data)


class PolicyTests(unittest.TestCase):
    def test_config_rejects_remote_and_injection(self):
        with self.assertRaises(ValueError):
            Endpoint("switch", 2000, "8.8.8.8")
        with self.assertRaises(ValueError):
            replace(config(), interface="GE0/0/1\nshutdown")
        with self.assertRaises(ValueError):
            replace(config(), source="192.168.10.2; reboot")
        with self.assertRaises(EnspError):
            require_allowed(config(), "OPS-SW1", "system-view")
        with self.assertRaises(EnspError):
            require_allowed(config(), "OPS-SW1", "display version\nreboot")

    def test_interface_exact_target_and_unknown(self):
        self.assertEqual(parse_interface("GE0/0/2 current state : UP\nLine protocol current state : UP", "GigabitEthernet0/0/1")["state"], "unknown")
        self.assertEqual(parse_interface("GigabitEthernet0/0/1 current state : UP", "GigabitEthernet0/0/1")["state"], "unknown")

    def test_ping_requires_complete_consistent_three_probes(self):
        for sent, received, loss, expected in [(3, 3, 0, "pass"), (3, 2, 33.33, "fail"), (3, 3, 100, "unknown"), (1, 1, 0, "unknown"), (0, 0, 0, "unknown")]:
            with self.subTest(sent=sent, received=received, loss=loss):
                output = f"{sent} packet(s) transmitted\n{received} packet(s) received\n{loss}% packet loss"
                self.assertEqual(parse_ping(output)["state"], expected)
        self.assertEqual(parse_ping("Reply from 192.168.10.1\n<SW>")["state"], "unknown")


class ServiceTests(unittest.TestCase):
    def test_fault_has_manual_plan_reference_and_evidence(self):
        report = fixture().diagnose()
        self.assertEqual(report["mode"], "fixture")
        self.assertEqual(report["diagnosis"]["code"], "administratively_down")
        self.assertEqual(report["repair_plan"]["execution"], "manual_only")
        self.assertIn("undo shutdown", report["repair_plan"]["commands"])
        self.assertEqual(report["references"][0]["pdf_page"], 209)
        self.assertEqual(len(report["commands"]), 5)
        self.assertIs(report["verification"]["passed"], False)

    def test_other_faults_do_not_get_shutdown_fix(self):
        for scenario, code in [("link-down", "link_down"), ("error-down", "error_down"), ("ping-failed", "path_unreachable"), ("unavailable", "insufficient_evidence")]:
            with self.subTest(scenario=scenario):
                report = fixture(scenario).diagnose()
                self.assertEqual(report["diagnosis"]["code"], code)
                self.assertIsNone(report["repair_plan"])
                self.assertIsNot(report["verification"]["passed"], True)

    def test_disabled_by_intent_does_not_get_repair(self):
        self.assertIsNone(fixture(cfg=replace(config(), expected_enabled=False)).diagnose()["repair_plan"])

    def test_recovery_requires_fresh_success_and_failed_baseline(self):
        service = fixture()
        before = service.diagnose()
        service.session_factory = fixture_factory(config(), "healthy")
        report = service.verify(before["run_id"])
        self.assertEqual(report["recovery"]["status"], "recovered")
        self.assertNotEqual(report["run_id"], before["run_id"])
        self.assertEqual(service.verify(report["run_id"])["recovery"]["status"], "healthy_without_failed_baseline")
        service.session_factory = fixture_factory(config(), "ping-failed")
        self.assertEqual(service.verify(before["run_id"])["recovery"]["status"], "not_recovered")

    def test_baseline_cannot_mix_modes_or_missing_keys(self):
        service = fixture()
        before = service.diagnose()
        for change, code in [({"mode": "live"}, "baseline_mismatch"), ({"config_fingerprint": "other"}, "baseline_mismatch"), ({"verification": {}}, "invalid_baseline")]:
            with self.subTest(change=change), self.assertRaises(EnspError) as caught:
                service.diagnose(before={**before, **change})
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(EnspError):
            service.verify("no-such-run")
        for invalid_id in ("", " ", []):
            with self.subTest(invalid_id=invalid_id), self.assertRaises(EnspError):
                service.verify(invalid_id)

    def test_history_is_not_mutated_by_caller(self):
        service = fixture()
        before = service.diagnose()
        before["verification"]["passed"] = True
        service.session_factory = fixture_factory(config(), "healthy")
        self.assertEqual(service.verify(before["run_id"])["recovery"]["status"], "recovered")

    def test_events_order_and_busy(self):
        service, events = fixture(), []
        service.diagnose(events.append)
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[0]["event"], "run_started")
        self.assertEqual(events[-2]["event"], "report")
        self.assertEqual(events[-1]["event"], "done")
        service._lock.acquire()
        try:
            with self.assertRaises(EnspError) as caught:
                service.health()
            self.assertEqual(caught.exception.code, "busy")
        finally:
            service._lock.release()

    def test_live_connection_failure_is_never_fixture(self):
        class Unavailable:
            last_output = ""
            def __init__(self, *args): pass
            def __enter__(self): raise EnspError("connection_failed", "test unavailable")
            def close(self): pass
        report = EnspService(config(), session_factory=Unavailable).diagnose()
        self.assertEqual(report["mode"], "live")
        self.assertIsNone(report["verification"]["passed"])
        self.assertEqual(report["commands"][0]["status"], "error")
        self.assertEqual(report["commands"][1]["status"], "skipped")

    def test_wrong_device_stops_collection(self):
        class WrongDevice:
            last_output = "unrelated software"
            def __init__(self, *args): pass
            def __enter__(self): return self
            def execute(self, command, callback): return self.last_output
            def close(self): pass
        report = EnspService(config(), session_factory=WrongDevice).diagnose()
        self.assertEqual(report["commands"][0]["error"]["code"], "unexpected_device")
        self.assertEqual(report["commands"][1]["status"], "skipped")


class TransportTests(unittest.TestCase):
    def test_fragmented_negotiation(self):
        codec = TelnetCodec()
        data, replies = bytearray(), bytearray()
        for byte in b"A\xff\xfb\x01\xff\xfd\x18\xff\xfa\x18\x01\xff\xf0B\xff\xff":
            text, reply = codec.feed(bytes([byte]))
            data.extend(text)
            replies.extend(reply)
        self.assertEqual(data, b"AB\xff")
        self.assertIn(b"\xff\xfd\x01", replies)
        self.assertIn(b"VT100", replies)

    def test_terminal_cleanup(self):
        self.assertEqual(clean_terminal("\x1b[32mAB\bC\r\n\x00<SW>"), "AC\n<SW>")

    def test_real_socket_paginated_command(self):
        def handle(sock):
            line(sock)
            sock.sendall(b"\r\n<SW>")
            command = line(sock)
            sock.sendall(command + b"Huawei Versatile Routing Platform Software\r\n---- More ----")
            if sock.recv(1) != b" ":
                return
            sock.sendall(b"\r\nVRP (R) software, Version 5.110\r\n<SW>")
            sock.recv(1)  # Keep the console open until the client closes it.
        with console(handle) as endpoint, ConsoleSession(endpoint, timeout=1) as session:
            chunks = []
            output = session.execute("display version", chunks.append)
            self.assertIn("VRP (R)", output)
            self.assertGreaterEqual(len(chunks), 2)

    def test_auth_and_wrong_view(self):
        for prompt, code in [(b"Password:", "authentication_required"), (b"[SW-GigabitEthernet0/0/1]", "wrong_view")]:
            def handle(sock):
                line(sock)
                sock.sendall(b"\r\n" + prompt)
                sock.recv(1)
            with self.subTest(code=code), console(handle) as endpoint, self.assertRaises(EnspError) as caught:
                with ConsoleSession(endpoint, timeout=1): pass
            self.assertEqual(caught.exception.code, code)

    def test_disconnect_partial_output_is_not_success(self):
        def handle(sock):
            line(sock)
            sock.sendall(b"\r\n<SW>")
            line(sock)
            sock.sendall(b"GigabitEthernet0/0/1 current state : UP\r\n")
        with console(handle) as endpoint, ConsoleSession(endpoint, timeout=1) as session:
            with self.assertRaises(EnspError) as caught:
                session.execute("display interface GigabitEthernet0/0/1")
            self.assertEqual(caught.exception.code, "disconnected")
            self.assertIn("current state", session.last_output)

    def test_timeout(self):
        def handle(sock):
            line(sock)
            time.sleep(0.15)
        with console(handle) as endpoint, self.assertRaises(EnspError) as caught:
            with ConsoleSession(endpoint, timeout=0.05): pass
        self.assertEqual(caught.exception.code, "timeout")

    def test_device_error_and_command_injection(self):
        def handle(sock):
            line(sock)
            sock.sendall(b"\r\n<SW>")
            line(sock)
            sock.sendall(b"\r\nError: Unrecognized command found at '^' position.\r\n<SW>")
            sock.recv(1)
        with console(handle) as endpoint, ConsoleSession(endpoint, timeout=1) as session:
            with self.assertRaises(EnspError) as caught:
                session.execute("display version\nreboot")
            self.assertEqual(caught.exception.code, "invalid_command")
            with self.assertRaises(EnspError) as caught:
                session.execute("display missing")
            self.assertEqual(caught.exception.code, "command_failed")

    def test_split_initial_prompts_do_not_shift_command_results(self):
        def handle(sock):
            sock.sendall(b"\r\n<SW>")
            line(sock)
            time.sleep(0.02)
            sock.sendall(b"\r\n<SW>")
            command = line(sock)
            sock.sendall(command + b"\r\nHuawei Versatile Routing Platform Software\r\n<SW>")
            sock.recv(1)
        with console(handle) as endpoint, ConsoleSession(endpoint, timeout=1) as session:
            self.assertIn("Huawei", session.execute("display version"))

    def test_output_is_bounded(self):
        def handle(sock):
            line(sock)
            sock.sendall(b"\r\n<SW>")
            line(sock)
            sock.sendall(b"x" * 270000)
        with console(handle) as endpoint, ConsoleSession(endpoint, timeout=1) as session:
            with self.assertRaises(EnspError) as caught:
                session.execute("display version")
            self.assertEqual(caught.exception.code, "output_limit")


class TcpWorkflowTests(unittest.TestCase):
    def test_prepare_fault_diagnose_restore_verify_over_tcp(self):
        # This is a stateful protocol simulator, not evidence of an actual eNSP run.
        state = {"down": False, "names": {"switch": "Huawei", "probe": "Huawei"}}
        seen = []

        def handler(role):
            def handle(sock):
                view = False
                while True:
                    packet = line(sock)
                    if not packet:
                        return
                    command = packet.decode().strip()
                    seen.append((role, command))
                    body = ""
                    if command == "display version":
                        body = "Huawei Versatile Routing Platform Software\r\nVRP (R) software, Version 5.110 (S5700 V200R001C00)"
                    elif command == "system-view":
                        view = True
                    elif command == "return":
                        view = False
                    elif command.startswith("sysname "):
                        state["names"][role] = command.split()[1]
                    elif command in ("shutdown", "undo shutdown") and role == "switch":
                        state["down"] = command == "shutdown"
                    elif command.startswith("display interface"):
                        physical = "Administratively DOWN" if state["down"] else "UP"
                        body = f"GigabitEthernet0/0/1 current state : {physical}\r\nLine protocol current state : {'DOWN' if state['down'] else 'UP'}"
                    elif command.startswith("display current-configuration"):
                        body = "#\r\ninterface GigabitEthernet0/0/1\r\n" + (" shutdown\r\n" if state["down"] else "") + "#"
                    elif command.startswith("ping "):
                        body = f"3 packet(s) transmitted\r\n{0 if state['down'] else 3} packet(s) received\r\n{100 if state['down'] else 0}.00% packet loss"
                    name = state["names"][role]
                    prompt = f"[{name}]" if view else f"<{name}>"
                    sock.sendall((command + "\r\n" + body + "\r\n" + prompt).encode())
            return handle

        with console(handler("switch")) as target, console(handler("probe")) as probe:
            cfg = LabConfig(Endpoint("OPS-SW1", target.port), Endpoint("OPS-PROBE", probe.port), timeout=2)
            operate(cfg, "prepare")
            service = EnspService(cfg)
            self.assertTrue(service.diagnose()["verification"]["passed"])
            operate(cfg, "fault")
            before = service.diagnose()
            self.assertEqual(before["diagnosis"]["code"], "administratively_down")
            operate(cfg, "restore")
            after = service.verify(before["run_id"])
            self.assertEqual(after["recovery"]["status"], "recovered")
            self.assertIn(("probe", "ping -c 3 -t 1000 -a 192.168.10.2 192.168.10.1"), seen)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.service = fixture()
        self.server = make_server(self.service, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, body=None, headers=None, method=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        all_headers = {"Content-Type": "application/json", **(headers or {})}
        conn.request(method or ("POST" if body is not None else "GET"), PREFIX + path, body, all_headers)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read().decode("utf-8")
        conn.close()
        return result

    def test_json_and_recovery(self):
        status, _, body = self.request("/diagnose", "{}")
        self.assertEqual(status, 200)
        before = json.loads(body)
        self.service.session_factory = fixture_factory(config(), "healthy")
        status, _, body = self.request("/verify", json.dumps({"before_run_id": before["run_id"]}))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["recovery"]["status"], "recovered")

    def test_sse(self):
        status, headers, body = self.request("/diagnose/stream", "{}")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/event-stream"))
        events = [json.loads(block.split("data: ", 1)[1]) for block in body.strip().split("\n\n")]
        self.assertEqual(events[0]["event"], "run_started")
        self.assertEqual(events[-1]["event"], "done")
        self.assertEqual(events[-2]["report"]["mode"], "fixture")

    def test_request_policy(self):
        for path, body, headers, status in [
            ("/diagnose", '{"command":"shutdown"}', {}, 400),
            ("/diagnose", "[]", {}, 400),
            ("/diagnose", "{", {}, 400),
            ("/diagnose", " " * 4097, {}, 400),
            ("/diagnose", "{}", {"Origin": "https://evil.example"}, 403),
            ("/diagnose", "{}", {"Origin": "null"}, 403),
            ("/diagnose", "{}", {"Host": "evil.example"}, 403),
            ("/diagnose", "{}", {"Content-Type": "text/plain"}, 400),
            ("/repair", "{}", {}, 404),
            ("/verify", '{"before_run_id":"missing"}', {}, 404),
        ]:
            with self.subTest(path=path, body=body[:50], headers=headers):
                self.assertEqual(self.request(path, body, headers)[0], status)

    def test_busy_and_cors(self):
        self.service._lock.acquire()
        try:
            self.assertEqual(self.request("/diagnose/stream", "{}")[0], 409)
        finally:
            self.service._lock.release()
        status, headers, _ = self.request("/config", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:5173")


if __name__ == "__main__":
    unittest.main()
