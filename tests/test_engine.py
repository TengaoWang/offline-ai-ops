import json
import shutil
import tempfile
import unittest
from pathlib import Path

from engine.executor import CommandRejected, Executor, validate_argv
from engine.rules import RuleError, evaluate, evaluate_rules
from engine.skill_engine import EngineError, SkillEngine
from engine.skill_loader import SkillLoader


ROOT = Path(__file__).resolve().parent.parent


class AllowlistTest(unittest.TestCase):
    def test_expected_read_only_commands_are_allowed(self):
        for argv in (["df", "-P"], ["ping", "-c", "1", "127.0.0.1"],
                     ["ps", "-axo", "pid,comm"], ["last", "-n", "5"]):
            self.assertEqual(validate_argv(list(argv)), list(argv))

    def test_dangerous_programs_are_rejected(self):
        for argv in (["rm", "-rf", "/"], ["reboot"], ["shutdown", "-h", "now"],
                     ["write", "memory"]):
            with self.assertRaises(CommandRejected, msg=str(argv)):
                validate_argv(list(argv))

    def test_shell_injection_is_rejected(self):
        payloads = ["1.1.1.1;rm", "1.1.1.1&&id", "1.1.1.1|cat", "`id`", "$(id)",
                    "1.1.1.1\nreboot", "1.1.1.1>out"]
        for payload in payloads:
            with self.assertRaises(CommandRejected, msg=payload):
                validate_argv(["ping", "-c", "1", payload])

    def test_required_timeout_stops_following_commands(self):
        commands = [
            {"id": "first", "argv": ["uptime"], "required": True,
             "simulation": {"status": "timeout", "output": ""}},
            {"id": "second", "argv": ["who"], "required": False,
             "simulation": {"status": "success", "output": "ops"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = Executor(tmp).execute(commands, "simulation")
        self.assertEqual([item["command_id"] for item in result], ["first"])

    def test_required_failure_stops_following_commands(self):
        commands = [
            {"id": "first", "argv": ["uptime"], "required": True,
             "simulation": {"status": "failed", "returncode": 1, "output": "failed"}},
            {"id": "second", "argv": ["who"], "required": False,
             "simulation": {"status": "success", "output": "ops"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = Executor(tmp).execute(commands, "simulation")
        self.assertEqual([item["command_id"] for item in result], ["first"])

    def test_zero_rule_value_is_not_rendered_as_unknown(self):
        rules = [{"id": "r1", "when": {"fact": "usage", "op": "eq", "value": 0},
                  "on_match": {"finding": {"title": "value ${usage}", "ref_ids": []}}}]
        _, findings = evaluate_rules(rules, {"usage": 0})
        self.assertEqual(findings[0]["title"], "value 0")


class RuleTreeTest(unittest.TestCase):
    def test_rule_path_and_finding_are_deterministic(self):
        rules = [{"id": "r1", "label": "usage", "when": {"fact": "usage", "op": "gte", "value": 90},
                  "on_match": {"branch": "warning", "finding": {"severity": "warning", "title": "full",
                  "symptom": "usage ${usage}%", "root_cause": "capacity", "fix_commands": [], "ref_ids": ["ref"]}}}]
        paths, findings = evaluate_rules(rules, {"usage": 95})
        self.assertTrue(paths[0]["matched"])
        self.assertEqual(paths[0]["branch"], "warning")
        self.assertEqual(findings[0]["symptom"], "usage 95%")

    def test_unknown_or_code_like_operator_is_rejected(self):
        with self.assertRaises(RuleError):
            evaluate({"fact": "x", "op": "__import__('os').system", "value": "id"}, {"x": 1})

    def test_regex_is_length_bounded(self):
        with self.assertRaises(RuleError):
            evaluate({"fact": "x", "op": "regex", "value": "x" * 201}, {"x": "x"})


class SkillPackageTest(unittest.TestCase):
    def test_four_seed_skills_are_valid_and_old_draft_is_not_executable(self):
        cards = SkillLoader(ROOT / "skills", ROOT).scan()
        valid = {item.id for item in cards if item.valid}
        self.assertTrue({"net-unreachable", "disk-full", "service-down", "log-audit"}.issubset(valid))
        old = next(item for item in cards if item.id == "saved-skill-1791027243")
        self.assertFalse(old.valid)

    def test_simulation_reports_are_sourced(self):
        engine = SkillEngine(ROOT / "skills", ROOT / "runtime", ROOT)
        for skill in ("disk-full", "service-down", "log-audit"):
            result = engine.run(skill, mode="simulation", enable_ai=False)
            self.assertGreaterEqual(len(result["findings"]), 3)
            self.assertTrue(all(finding["sources"] for finding in result["findings"]))
            self.assertEqual(result["execution_mode"], "simulation")

    def test_ai_finding_must_cite_this_turn_and_supported_command(self):
        hit = {"id": 1, "file": "manual.pdf", "section": "interface", "page": 7,
               "text": "执行 display interface brief 查看接口状态。",
               "label": "《manual》 interface P7", "score": 1.0}
        reply = json.dumps({"findings": [{"severity": "warning",
                            "evidence_quote": "执行 display interface brief 查看接口状态。",
                            "fix_commands": ["display interface brief"], "citations": [1]}],
                            "unresolved": []})
        engine = SkillEngine(ROOT / "skills", ROOT / "runtime", ROOT,
                             retriever=lambda query, k=5: [hit], chat_fn=lambda *a, **k: reply)
        result = engine.run("net-unreachable", mode="simulation")
        ai = [item for item in result["findings"] if item["judged_by"] == "ai"]
        self.assertEqual(len(ai), 1)
        self.assertEqual(ai[0]["sources"][0]["page"], 7)

    def test_ai_finding_without_citation_becomes_unresolved(self):
        hit = {"id": 1, "file": "manual.pdf", "section": "s", "page": 1, "text": "source", "score": 1.0}
        reply = json.dumps({"findings": [{"severity": "warning", "evidence_quote": "guess",
                            "fix_commands": [], "citations": []}], "unresolved": []})
        engine = SkillEngine(ROOT / "skills", ROOT / "runtime", ROOT,
                             retriever=lambda query, k=5: [hit], chat_fn=lambda *a, **k: reply)
        result = engine.run("net-unreachable", mode="simulation")
        self.assertFalse(any(item["judged_by"] == "ai" for item in result["findings"]))
        self.assertTrue(any("没有合法出处编号" in item for item in result["unresolved"]))

    def test_save_skill_is_valid_atomic_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "skills").mkdir()
            (project / "docs").mkdir()
            shutil.copytree(ROOT / "skills" / "disk-full", project / "skills" / "disk-full")
            shutil.copyfile(ROOT / "docs" / "内置离线运维诊断基线.md", project / "docs" / "内置离线运维诊断基线.md")
            engine = SkillEngine(project / "skills", project / "runtime", project)
            run = engine.run("disk-full", mode="simulation", enable_ai=False)
            saved = engine.save_skill(run, "复用磁盘检查", "saved-disk-check")
            self.assertTrue((project / "skills" / saved["skill_id"] / "collect.yaml").is_file())
            self.assertTrue(engine.loader.load(saved["skill_id"]).valid)
            with self.assertRaises(EngineError):
                engine.save_skill(run, "复用磁盘检查", "saved-disk-check")


if __name__ == "__main__":
    unittest.main()
