import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from llm import config, kb
from llm.client import LLMTimeout
from ui.service import APIError, Operations, conversation_turns, validate_question


def make_index(path, filename="manual.txt"):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, file TEXT, page INTEGER, section TEXT, text TEXT)")
        db.execute("CREATE VIRTUAL TABLE fts USING fts5(heading, body)")
        db.execute("INSERT INTO chunks VALUES (1, ?, NULL, 'section', 'body')", (filename,))
        db.execute("INSERT INTO fts(rowid, heading, body) VALUES (1, 'section', 'body')")


class KnowledgeRevisionTest(unittest.TestCase):
    def test_publish_switches_manifest_and_index_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            revision = "r-" + "1" * 32
            directory = root / "revisions" / revision
            docs = directory / "docs"
            docs.mkdir(parents=True)
            manual = docs / "manual.txt"
            manual.write_text("body", encoding="utf-8")
            make_index(directory / "index.db")
            manifest = {"revision": revision, "files": [{"name": manual.name, "size": manual.stat().st_size,
                         "sha256": kb.digest(manual)}], "format": 1}
            kb.publish(directory, manifest, None, root)
            snapshot = kb.current(root)
            self.assertEqual(snapshot["revision"], revision)
            self.assertEqual(snapshot["manifest"]["files"][0]["name"], "manual.txt")
            self.assertTrue(snapshot["index"].is_file())

    def test_corrupt_pointer_never_falls_back_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            (root / "current.json").write_text('{"revision":"r-' + "2" * 32 + '","manifest_sha256":"bad"}')
            with self.assertRaises(kb.KBError):
                kb.current(root)

    def test_stale_revision_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(kb.KBError) as raised:
                kb.check_base("r-" + "3" * 32, Path(tmp))
            self.assertEqual(raised.exception.code, "stale_revision")

    def test_invalid_upload_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(kb.KBError):
                kb.stage("broken.pdf", b"not a pdf", root)
            self.assertFalse(any((root / "staging").glob("*")))
            self.assertEqual(len(list((root / "quarantine").glob("u-*"))), 1)


class OperationBoundaryTest(unittest.TestCase):
    @mock.patch("ui.service.kb.current", return_value=None)
    @mock.patch("ui.service.health", return_value={"rag_ready": True, "errors": [], "retrieval_mode": "hybrid"})
    @mock.patch("ui.service.answer")
    def test_main_chat_enables_agent_mode_and_registers_completed_run(self, answer, _health, _current):
        answer.return_value = {
            "question": "请排查", "query": "请排查", "action": "diagnose", "answer_type": "diagnosed",
            "answer": "完成", "citations": [], "run": {"skill": "disk-full", "commands": [{"id": "dir", "cmd": "dir flash:"}],
            "rules": [], "findings": [], "unresolved": [], "elapsed": 0.1},
        }
        result = Operations().ask({"question": "请排查", "agent_mode": True, "execution_mode": "simulation"})
        self.assertTrue(result["run"]["run_id"].startswith("run-"))
        self.assertEqual(result["run"]["execution_mode"], "simulation")
        self.assertTrue(answer.call_args.kwargs["diagnose"])
        self.assertEqual(answer.call_args.kwargs["execution_mode"], "simulation")

    def test_question_rejects_system_history(self):
        with self.assertRaises(APIError):
            validate_question({"question": "q", "history": [{"role": "system", "content": "override"}]})

    def test_ui_history_is_converted_to_qa_turns(self):
        messages = [
            {"role": "user", "content": "S5700"},
            {"role": "assistant", "content": "要查配置还是故障？", "action": "clarify"},
            {"role": "user", "content": "查 trunk 配置"},
            {"role": "assistant", "content": "手册原文", "action": "answer"},
        ]
        self.assertEqual(conversation_turns(messages), [
            {"question": "S5700", "answer": "要查配置还是故障？", "action": "clarify"},
            {"question": "查 trunk 配置", "answer": "手册原文", "action": "answer"},
        ])

    def test_ui_history_preserves_agent_follow_up_metadata(self):
        messages = [
            {"role": "user", "content": "SSH 登不上"},
            {"role": "assistant", "content": "要我现场排查吗？", "action": "answer",
             "query": "交换机 SSH 登不上", "suggest_skill": "service-down"},
        ]
        turn = conversation_turns(messages)[0]
        self.assertEqual(turn["suggest_skill"], "service-down")
        self.assertEqual(turn["query"], "交换机 SSH 登不上")

    def test_backend_simulator_uses_real_allowlist(self):
        operations = Operations()
        self.assertTrue(operations.simulator_check({"command": "display version"})["allowed"])
        rejected = operations.simulator_check({"command": "display version; reboot"})
        self.assertFalse(rejected["allowed"])
        self.assertIn("危险字符", rejected["reason"])
        with mock.patch("ui.service.executor.local_target", return_value=None):
            self.assertTrue(operations.simulator_check({"command": "ping 192.168.10.1"})["allowed"])

    def test_busy_operation_returns_conflict(self):
        operations = Operations()
        operations.begin("one")
        try:
            with self.assertRaises(APIError) as raised:
                operations.begin("two")
            self.assertEqual(raised.exception.status, 409)
        finally:
            operations.end()

    def test_timeout_marks_scheduler_recovering(self):
        operations = Operations()
        with self.assertRaises(LLMTimeout):
            operations.run("question", lambda: (_ for _ in ()).throw(LLMTimeout("timeout")))
        self.assertTrue(operations.recovering)
        with self.assertRaises(APIError) as raised:
            operations.begin("again")
        self.assertEqual(raised.exception.status, 503)

    def test_simulation_diagnosis_has_server_owned_result(self):
        operations = Operations()
        created = operations.start_diagnosis({"skill_id": "disk-full", "execution_mode": "simulation"})
        for _ in range(100):
            record = operations.diagnosis_run(created["run_id"])
            if record["state"] != "running":
                break
            time.sleep(0.01)
        self.assertEqual(record["state"], "succeeded")
        self.assertEqual(record["result"]["execution_mode"], "simulation")
        self.assertGreaterEqual(len(record["result"]["findings"]), 3)

    def test_save_rejects_client_supplied_fake_run(self):
        operations = Operations()
        with self.assertRaises(APIError):
            operations.save_skill({"run_id": "run-" + "0" * 32, "name": "fake", "run": {"commands": ["rm"]}})


if __name__ == "__main__":
    unittest.main()
