import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from engine.simulator import SimulatorError, normalize_simulator_target, validate_simulator_mapping
from engine.skill_engine import EngineError, SkillEngine


ROOT = Path(__file__).resolve().parent.parent


class FakeSwitchHandler(BaseHTTPRequestHandler):
    epoch = "integration-epoch"
    calls = []

    def log_message(self, *_):
        pass

    def send_json(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers["Content-Length"])))

    def do_GET(self):
        self.calls.append(("GET", self.path, None))
        if self.path == "/api/v1/health":
            self.send_json({"api_version": "1.0", "service": "fieldnote-switch-simulator",
                            "status": "ready", "epoch": self.epoch, "revision": 0,
                            "devices": ["PC1", "SW1", "SW2"]})
        elif self.path == "/api/v1/observation":
            self.send_json({"api_version": "1.0", "epoch": self.epoch, "revision": 0,
                            "symptom": "test", "devices": ["PC1", "SW1", "SW2"], "links": []})
        elif self.path == "/api/v1/logs":
            self.send_json({"epoch": self.epoch, "revision": 0, "logs": []})
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        body = self.body()
        self.calls.append(("POST", self.path, body))
        if self.path == "/api/v1/context":
            self.send_json({"device": body["device"], "prompt": ">", "epoch": self.epoch, "revision": 0})
            return
        if self.path == "/api/v1/probe":
            self.send_json({"api_version": "1.0", "probe": {"epoch": self.epoch, "revision": 0,
                            "passed": False, "status": "failed", "results": [{"passed": False}]}})
            return
        if self.path == "/api/v1/diagnose":
            self.send_json({"api_version": "1.0", "diagnosis": {"epoch": self.epoch, "revision": 0,
                            "fault_code": "E", "category": "handoff", "title": "physical",
                            "reason": "field work required"}})
            return
        if self.path == "/api/v1/repair":
            self.send_json({"api_version": "1.0", "repair": {"epoch": self.epoch, "revision": 0,
                            "eligible": False, "repaired": False, "records": [],
                            "probe": {"passed": False}}})
            return
        if self.path == "/api/v1/command":
            command = body["command"]
            outputs = {
                "ping 192.168.10.11": "3 packet(s) transmitted\n0 packet(s) received\n100% packet loss",
                "display interface brief": "Interface PHY Protocol\nGigabitEthernet0/0/1 UP UP",
                "display port vlan": "Port Link Type PVID\nGigabitEthernet0/0/1 access 10",
                "display ip routing-table": "Destination/Mask Proto NextHop Interface\n192.168.10.0/24 Direct 192.168.10.1 Vlanif10",
            }
            record = {"device": body["device"], "command": command, "output": outputs[command],
                      "ok": True, "mutation": False, "revision": 0, "epoch": self.epoch}
            self.send_json({"api_version": "1.0", "records": [record], "skipped": 0,
                            "observation": {"epoch": self.epoch, "revision": 0}})
            return
        self.send_json({"error": "not found"}, 404)


class SimulatorTargetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FakeSwitchHandler.calls = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSwitchHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.target = {"kind": "simulator", "display_name": "test-switch-lab",
                      "base_url": f"http://127.0.0.1:{cls.server.server_port}/api/v1"}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def test_target_and_command_policy_reject_remote_or_write_access(self):
        with self.assertRaises(SimulatorError):
            normalize_simulator_target({"kind": "simulator", "base_url": "http://example.com:8878/api/v1"})
        with self.assertRaises(SimulatorError):
            validate_simulator_mapping({"action": "command", "device": "SW1", "command": "system-view"})

    def test_switch_skill_runs_through_loopback_api(self):
        FakeSwitchHandler.calls = []
        engine = SkillEngine(ROOT / "skills", ROOT / "runtime", ROOT)
        result = engine.run("switch-lab-connectivity", target=self.target, mode="simulation", enable_ai=False)
        self.assertEqual(result["execution_mode"], "simulation")
        self.assertEqual(result["target"]["kind"], "simulator")
        self.assertEqual(len(result["collected"]), 2)
        self.assertTrue(all(item["status"] == "success" for item in result["collected"]))
        self.assertTrue(all(item.get("simulator", {}).get("epoch") == FakeSwitchHandler.epoch
                            for item in result["collected"]))
        self.assertEqual(len(result["findings"]), 1)
        paths = [path for _, path, _ in FakeSwitchHandler.calls]
        self.assertEqual(paths[:2], ["/api/v1/health", "/api/v1/observation"])
        self.assertEqual(paths.count("/api/v1/probe"), 1)
        self.assertIn("/api/v1/diagnose", paths)

    def test_switch_skill_requires_simulation_mode(self):
        engine = SkillEngine(ROOT / "skills", ROOT / "runtime", ROOT)
        with self.assertRaises(EngineError):
            engine.run("switch-lab-connectivity", target=self.target, mode="real", enable_ai=False)


if __name__ == "__main__":
    unittest.main()
