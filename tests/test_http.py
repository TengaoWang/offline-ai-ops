import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import ui.server as server_module
from llm.client import LLMError, LLMProtocolError, LLMTimeout


class FakeOperations:
    def status(self):
        return {"busy": False, "operation": None, "recovering": False}

    def list_skills(self):
        return [{"id": "disk-full", "name": "disk", "description": "d", "command_count": 1,
                 "source": "skills/", "valid": True, "errors": [], "demo_ready": True}]

    def ask(self, payload):
        return {"answer_type": "generated", "answer": "ok", "citations": [],
                "execution_mode": "mock", "request_id": payload.get("request_id")}

    def start_diagnosis(self, payload):
        return {"run_id": "run-" + "1" * 32, "state": "running", "execution_mode": payload["execution_mode"]}

    def diagnosis_run(self, identifier):
        return {"run_id": identifier, "state": "succeeded", "result": {"findings": []}}

    def diagnosis_events(self, identifier, after=0):
        yield {"sequence": 1, "event": "start", "data": {"run_id": identifier, "execution_mode": "simulation"}}
        yield {"sequence": 2, "event": "done", "data": {"run_id": identifier, "findings": []}}

    def save_skill(self, payload):
        return {"skill_id": "saved-test", "path": "/tmp/saved-test", "skill": {"id": "saved-test"}}

    def list_memories(self):
        return {"memories": [{"id": 7, "kind": "fact", "text": "MES=192.168.10.20"}],
                "facts_count": 1, "episodes_count": 0}

    def forget_memory(self, identifier):
        return {"ok": True, "memory_id": int(identifier)}

    def simulator_check(self, payload):
        command = payload["command"]
        return {"command": command, "allowed": ";" not in command,
                "reason": "ok" if ";" not in command else "包含危险字符", "simulated": True}


class HTTPContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_operations, cls.old_health = server_module.operations, server_module.health
        server_module.operations = FakeOperations()
        server_module.health = lambda: {"mock": True, "rag_ready": True, "index": True, "chunks": 1,
                                         "vectors": 1, "errors": [], "backend": "ollama"}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), server_module.UIHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        server_module.operations, server_module.health = cls.old_operations, cls.old_health

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=data,
                                         headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read(), response.headers.get_content_type()

    def error_request(self, path, payload):
        data = json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())
        self.fail("expected HTTP error")

    def test_ask_contract(self):
        status, data, content_type = self.request("/api/ask", {"question": "q", "request_id": "r"})
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(data)["execution_mode"], "mock")

    def test_diagnosis_create_status_and_closed_sse(self):
        status, data, _ = self.request("/api/diagnose/runs", {"skill_id": "disk-full", "execution_mode": "simulation"})
        self.assertEqual(status, 202)
        run_id = json.loads(data)["run_id"]
        status, stream, content_type = self.request(f"/api/diagnose/runs/{run_id}/events")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/event-stream")
        self.assertIn(b"event: start", stream)
        self.assertIn(b"event: done", stream)
        status, data, _ = self.request(f"/api/diagnose/runs/{run_id}")
        self.assertEqual(json.loads(data)["state"], "succeeded")

    def test_save_skill_uses_run_id_contract(self):
        status, data, _ = self.request("/api/skills/save", {"run_id": "run-" + "1" * 32, "name": "saved"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["skill_id"], "saved-test")

    def test_memory_list_delete_and_backend_simulator_contracts(self):
        status, data, _ = self.request("/api/memory")
        self.assertEqual((status, json.loads(data)["facts_count"]), (200, 1))
        request = urllib.request.Request(self.base + "/api/memory/7", method="DELETE")
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(json.loads(response.read())["memory_id"], 7)
        status, data, _ = self.request("/api/simulator/check", {"command": "display version"})
        self.assertTrue(json.loads(data)["allowed"])
        status, data, _ = self.request("/api/simulator/check", {"command": "display version; reboot"})
        self.assertFalse(json.loads(data)["allowed"])

    def test_model_errors_map_to_502_503_504_and_never_200(self):
        original = server_module.operations.ask
        try:
            for error, expected, code in ((LLMProtocolError("bad json"), 502, "model_protocol_error"),
                                          (LLMError("offline"), 503, "model_unavailable"),
                                          (LLMTimeout("slow"), 504, "model_timeout")):
                server_module.operations.ask = lambda payload, error=error: (_ for _ in ()).throw(error)
                status, body = self.error_request("/api/ask", {"question": "q"})
                self.assertEqual((status, body["code"]), (expected, code))
        finally:
            server_module.operations.ask = original


if __name__ == "__main__":
    unittest.main()
