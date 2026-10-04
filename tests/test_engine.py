"""诊断引擎测试。不需要 Ollama 和真实设备：本机命令用假的执行函数，交换机命令用回放，AI 判定关闭。

运行：.venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import executor, rules, runner, skillgen  # noqa: E402
from engine.loader import SKILLS_DIR, all_ref_sections, list_skills, load_skill  # noqa: E402
from llm import config  # noqa: E402
from llm.cite import cite, missing_sections  # noqa: E402

DEMO_SKILLS = ["net-unreachable", "disk-full", "service-down", "log-audit"]
WIN_UNREACHABLE = """正在 Ping 192.168.10.20 具有 32 字节的数据:
来自 192.168.10.1 的回复: 无法访问目标主机。
来自 192.168.10.1 的回复: 无法访问目标主机。

192.168.10.20 的 Ping 统计信息:
    数据包: 已发送 = 2，已接收 = 2，丢失 = 0 (0% 丢失)，"""


class WhitelistTest(unittest.TestCase):
    def assertRejected(self, command, target="local"):
        ok, reason = executor.check(command, target)
        self.assertFalse(ok, f"应拒绝：{command}")
        result = executor.execute(command, target, runner=lambda *a: self.fail("被拒绝的命令不应执行"))
        self.assertEqual(result["status"], "rejected")
        self.assertIn(executor.REJECTED_TEXT, result["output"])

    def test_injection_is_rejected(self):
        for command in ["ping 1.1.1.1; rm -rf /", "ping 1.1.1.1 & del C:\\*", "ping 1.1.1.1 && shutdown -s",
                        "ping 1.1.1.1 | findstr TTL", "ping `whoami`", "ping $(whoami)", "ipconfig > a.txt",
                        "ping %COMPUTERNAME%", "ping 1.1.1.1\nshutdown"]:
            self.assertRejected(command)

    def test_not_whitelisted(self):
        for command in ["del C:\\Windows", "shutdown /s", "netsh interface set interface x disable",
                        "powershell -c ls", "rm -rf /", "format C:"]:
            self.assertRejected(command)

    def test_argument_limits(self):
        self.assertRejected("ping -n 1000 1.1.1.1")      # 次数超过 4
        self.assertRejected("ping -t 1.1.1.1")           # 一直 ping
        self.assertRejected("ping -n 2 1.1.1.1 2.2.2.2")  # 多个目标
        self.assertRejected("tracert -h 30 1.1.1.1")     # 跳数超过 10
        self.assertRejected("ipconfig /release")         # 会改网络配置
        self.assertTrue(executor.check("ping -n 2 -w 1000 192.168.10.1")[0])
        self.assertTrue(executor.check("tracert -d -h 8 -w 500 server01")[0])
        self.assertTrue(executor.check("ipconfig /all")[0])

    def test_switch_commands(self):
        for command in ["display interface brief", "display port vlan", "dir /all flash:", "display startup"]:
            self.assertTrue(executor.check(command, "switch")[0], command)
        for command in ["save", "reset recycle-bin", "undo shutdown", "system-view", "reboot", "write memory",
                        "delete /unreserved flash:/a.cc", "display interface brief | include up"]:
            self.assertRejected(command, "switch")
        self.assertFalse(executor.check("display interface", "local")[0])  # 交换机命令不能在本机执行

    def test_live_execution_without_shell(self):
        calls = []

        def fake(args, timeout):
            calls.append((args, timeout))
            return 0, "来自 192.168.10.1 的回复: TTL=255".encode("gbk")

        old = os.environ.get("ENGINE_MODE")
        os.environ["ENGINE_MODE"] = "live"
        try:
            result = executor.execute("ping -n 2 -w 1000 192.168.10.1", runner=fake, timeout=5)
            self.assertEqual(calls, [(["ping", "-n", "2", "-w", "1000", "192.168.10.1"], 5)])  # 参数列表，不经过 shell
            self.assertEqual(result["status"], "success")
            self.assertIn("来自", result["raw"])  # GBK 正确解码

            def slow(args, timeout):
                raise subprocess.TimeoutExpired(args, timeout)

            self.assertEqual(executor.execute("arp -a", runner=slow)["status"], "timeout")
        finally:
            if old is None:
                os.environ.pop("ENGINE_MODE")
            else:
                os.environ["ENGINE_MODE"] = old


class RulesTest(unittest.TestCase):
    def test_unreachable_reply_from_gateway_counts_as_unreachable(self):
        """Windows 上网关代回「无法访问目标主机」时丢包率是 0%，必须按「没有 TTL=」判断。"""
        check = {"cmd": "ping", "not_regex": "TTL="}
        hit, _, _ = rules.evaluate(check, {"ping": {"status": "success", "raw": WIN_UNREACHABLE}}, {})
        self.assertTrue(hit)

    def test_numeric_check_and_variables(self):
        check = {"cmd": "dir", "extract": r"(?P<total>[\d,]+) KB total \((?P<free>[\d,]+) KB free\)",
                 "expr": "(total - free) * 100 / total", "op": ">", "value": "${threshold}"}
        results = {"dir": {"status": "success", "raw": "14,632 KB total (1,083 KB free)"}}
        hit, captured, _ = rules.evaluate(check, results, {"threshold": "90"})
        self.assertTrue(hit)
        self.assertEqual(captured["value"], "92.6")
        results = {"dir": {"status": "success", "raw": "14,632 KB total (8,228 KB free)"}}
        self.assertFalse(rules.evaluate(check, results, {"threshold": "90"})[0])

    def test_missing_output_is_unknown(self):
        tree = {"start": "a", "rules": [{"id": "a", "label": "A", "check": {"cmd": "x", "regex": "y"},
                                          "hit": {"branch": "是", "next": "end"}, "miss": {"branch": "否", "next": "end"}}]}
        outcome = rules.walk(tree, {"x": {"status": "failed", "raw": ""}}, {})
        self.assertEqual(outcome["path"][0]["state"], "miss")
        self.assertTrue(outcome["unresolved"])


class SkillsTest(unittest.TestCase):
    def setUp(self):
        self._mode = os.environ.get("ENGINE_MODE")
        os.environ["ENGINE_MODE"] = "replay"  # 本机命令也读回放，结果和平台无关
        self.tmp = tempfile.TemporaryDirectory()
        self.skills = Path(self.tmp.name) / "skills"
        shutil.copytree(SKILLS_DIR, self.skills)

    def tearDown(self):
        if self._mode is None:
            os.environ.pop("ENGINE_MODE", None)
        else:
            os.environ["ENGINE_MODE"] = self._mode
        self.tmp.cleanup()

    def test_all_demo_skills_are_valid(self):
        skills = {s["id"]: s for s in list_skills(self.skills)}
        for skill_id in DEMO_SKILLS:
            self.assertTrue(skills[skill_id]["valid"], (skill_id, skills[skill_id]["errors"]))

    def test_old_format_skill_is_flagged_not_crashing(self):
        old = self.skills / "old-skill"
        old.mkdir()
        (old / "collect.yaml").write_text('commands:\n  - "ipconfig | findstr 192.168"\n', encoding="utf-8")
        skill = load_skill(old)
        self.assertFalse(skill["valid"])
        self.assertTrue(skill["errors"])

    def test_each_skill_reports_three_graded_findings(self):
        """FR-6：每个技能至少 3 条分级项，每条有现象、根因；事件和 DEMO_RUNS 的字段一致。"""
        for skill_id in DEMO_SKILLS:
            events = list(runner.run_skill(skill_id, skills_dir=self.skills, use_ai=False))
            names = [e for e, _ in events]
            self.assertEqual(names[0], "start")
            self.assertEqual(names[-2:], ["report", "done"])
            done = events[-1][1]
            for key in ("skill", "commands", "rules", "ai_reasoning", "findings", "unresolved", "elapsed"):
                self.assertIn(key, done)
            findings = done["findings"]
            if skill_id == "log-audit":  # 第 3 条来自 AI 补充判定，这里关闭了 AI，改为列入未完成项
                self.assertGreaterEqual(len(findings), 2)
                self.assertTrue(any("规则未覆盖" in u for u in done["unresolved"]))
            else:
                self.assertGreaterEqual(len(findings), 3, skill_id)
            for finding in findings:
                self.assertIn(finding["severity"], {"critical", "warning", "ok"})
                self.assertTrue(finding["symptom"] and finding["root_cause"], finding)
                self.assertNotIn("${", finding["title"] + finding["symptom"], finding)
            for rule in done["rules"]:
                self.assertEqual(set(rule), {"id", "label", "state", "branch"})

    def test_network_tree_takes_different_branches(self):
        """FR-4：端口 down 和端口正常（VLAN 错）两份输出，判定路径不同。"""
        vlan = runner.run_skill_sync("net-unreachable", skills_dir=self.skills, use_ai=False)
        self.assertEqual(vlan["findings"][0]["title"], "端口 GigabitEthernet0/0/8 的 VLAN 划分错误")
        replay = self.skills / "net-unreachable" / "replay" / "if-brief.txt"
        replay.write_text(replay.read_text(encoding="utf-8").replace(
            "GigabitEthernet0/0/8  up     up", "GigabitEthernet0/0/8  down   down"), encoding="utf-8")
        down = runner.run_skill_sync("net-unreachable", skills_dir=self.skills, use_ai=False)
        self.assertEqual(down["findings"][0]["title"], "交换机端口 GigabitEthernet0/0/8 物理 down")
        self.assertNotEqual([r["id"] for r in vlan["rules"]], [r["id"] for r in down["rules"]])

    def test_injection_demo_is_blocked(self):
        run = runner.run_skill_sync("log-audit", skills_dir=self.skills, use_ai=False)
        injection = next(c for c in run["commands"] if c["id"] == "injection-demo")
        self.assertEqual(injection["status"], "rejected")
        self.assertIn("该命令不在白名单，已拒绝", injection["output"])

    def test_collect_budget(self):
        """FR-3：超过采集时限后，后面的命令不再执行，列为未完成项。"""
        old = runner.COLLECT_BUDGET
        runner.COLLECT_BUDGET = -1
        try:
            run = runner.run_skill_sync("disk-full", skills_dir=self.skills, use_ai=False)
        finally:
            runner.COLLECT_BUDGET = old
        self.assertTrue(all(c["status"] == "timeout" for c in run["commands"]))
        self.assertTrue(run["unresolved"])

    def test_save_skill_round_trip(self):
        """FR-8：把一次执行结果存成新技能，新技能格式正确，并且能直接执行。"""
        run = json.loads(json.dumps(runner.run_skill_sync("net-unreachable", skills_dir=self.skills, use_ai=False)))
        result = skillgen.build("现场 VLAN 排查", run, skills_dir=self.skills, slug="field-vlan")
        self.assertEqual(result["errors"], [])
        again = runner.run_skill_sync(result["skill_id"], skills_dir=self.skills, use_ai=False)
        self.assertEqual(again["findings"][0]["title"], run["findings"][0]["title"])


@unittest.skipUnless(config.INDEX_PATH.exists(), "需要手册索引 kb/index.db")
class CiteTest(unittest.TestCase):
    def test_section_number_matches_exactly(self):
        source = cite(["8.2"])[0]
        self.assertIn("8.2 接口物理DOWN故障定位指导", source["label"])
        self.assertNotIn("8.2.1", source["section"])
        self.assertEqual(source["via"], "section")

    def test_unknown_section_returns_empty(self):
        self.assertEqual(cite(["99.99"]), [])

    def test_all_skill_refs_exist_in_manual(self):
        """FR-7：所有技能 refs.yaml 里的章节号都能在手册里找到。"""
        for skill in list_skills():
            if skill["valid"]:
                self.assertEqual(missing_sections(all_ref_sections(skill)), [], skill["id"])


if __name__ == "__main__":
    unittest.main()
