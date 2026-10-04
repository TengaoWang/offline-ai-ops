"""长期记忆和对话里「排查」动作的测试。不需要 Ollama：向量检索关闭（退回关键词），模型调用用假的。

运行：.venv/bin/python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm import config, diagnose, memory, qa  # noqa: E402


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(memory, "MEMORY_DB", Path(self.tmp.name) / "m.db"),
                        mock.patch.object(memory, "MEMORY_DIR", Path(self.tmp.name) / "memory"),
                        mock.patch.object(config, "EMBED_MODEL", "")]  # 不算向量，检索走关键词
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_add_search_and_markdown_files(self):
        fact = memory.add("fact", "MES 服务器的业务地址是 192.168.10.20",
                          {"var": "target", "value": "192.168.10.20"}, "net-unreachable")
        memory.add("episode", "问题：MES 连不上。结论：端口 VLAN 划分错误。", {}, "net-unreachable")
        self.assertEqual(memory.facts_for("net-unreachable"), {"target": "192.168.10.20"})
        self.assertEqual(memory.search("MES 服务器又连不上", kind="fact")[0]["id"], fact["id"])
        files = sorted(p.name for p in memory.MEMORY_DIR.iterdir())
        self.assertEqual(files, ["MEMORY.md", "episode-0002.md", "fact-0001.md"])

    def test_same_variable_updates_instead_of_duplicating(self):
        memory.add("fact", "MES 地址 192.168.10.20", {"var": "target", "value": "192.168.10.20"}, "net-unreachable")
        memory.add("fact", "MES 地址改成 192.168.10.21", {"var": "target", "value": "192.168.10.21"}, "net-unreachable")
        self.assertEqual(len(memory.list_memories("fact")), 1)
        self.assertEqual(memory.facts_for("net-unreachable"), {"target": "192.168.10.21"})

    def test_edits_and_deletes_in_files_sync_back(self):
        a = memory.add("fact", "旧的说法", {}, None)
        b = memory.add("fact", "要删掉的", {}, None)
        path = memory.MEMORY_DIR / f"fact-{a['id']:04d}.md"
        path.write_text(path.read_text(encoding="utf-8").replace("旧的说法", "人工改过的说法"), encoding="utf-8")
        (memory.MEMORY_DIR / f"fact-{b['id']:04d}.md").unlink()
        self.assertEqual(memory.sync_from_files(), {"updated": 1, "deleted": 1})
        self.assertEqual([m["text"] for m in memory.list_memories()], ["人工改过的说法"])

    def test_forget(self):
        m = memory.add("episode", "一次排查", {}, None)
        self.assertTrue(memory.forget(m["id"]))
        self.assertEqual(memory.list_memories(), [])


class DispatchGuardTest(unittest.TestCase):
    """调度器的代码保护：只有明确要求动手查才执行技能；参数只接受用户的话或记忆里出现过的值。"""

    skills = [{"id": "net-unreachable", "name": "网络连通排查", "description": "", "vars": {"target": "", "port": ""}}]

    def dispatch(self, question, reply, history=None, recalled=None):
        with mock.patch.object(config, "MOCK", False), mock.patch.object(qa, "chat", return_value=json.dumps(reply)):
            return qa.dispatch(question, history, skills=self.skills, recalled=recalled or {"facts": [], "episodes": []})

    def test_explicit_request_runs_skill(self):
        reply = {"action": "diagnose", "clarify_question": "", "query": "q", "skill": "net-unreachable",
                 "vars": [{"name": "target", "value": "192.168.10.20"}, {"name": "port", "value": "未知"}], "facts": []}
        result = self.dispatch("MES 192.168.10.20 连不上了，帮我查一下", reply)
        self.assertEqual(result["action"], "diagnose")
        self.assertEqual(result["vars"], [{"name": "target", "value": "192.168.10.20"}])  # 「未知」是编造的，丢掉

    def test_symptom_only_answers_from_manual_and_suggests(self):
        reply = {"action": "diagnose", "clarify_question": "", "query": "q", "skill": "net-unreachable",
                 "vars": [], "facts": []}
        result = self.dispatch("网口灯不亮，网线插上也没反应", reply)
        self.assertEqual(result["action"], "answer")
        self.assertEqual(result["suggest_skill"], "net-unreachable")
        # 下一轮回答「好」：执行上一轮建议的技能
        agreed = self.dispatch("好", {"action": "answer", "clarify_question": "", "query": "好", "skill": "",
                                     "vars": [], "facts": []},
                               history=[{"question": "网口灯不亮", "query": "网口灯不亮", "action": "answer",
                                         "answer": "…", "suggest_skill": "net-unreachable"}])
        self.assertEqual((agreed["action"], agreed["skill"]), ("diagnose", "net-unreachable"))

    def test_value_from_memory_and_port_alias(self):
        reply = {"action": "diagnose", "clarify_question": "", "query": "q", "skill": "net-unreachable",
                 "vars": [{"name": "port", "value": "GigabitEthernet0/0/8"}], "facts": []}
        recalled = {"facts": [{"text": "MES 服务器接在交换机 GE0/0/8", "data": {}, "skill": None}], "episodes": []}
        result = self.dispatch("MES 又连不上了，帮我排查一下", reply, recalled=recalled)
        self.assertEqual(result["vars"], [{"name": "port", "value": "GigabitEthernet0/0/8"}])
        self.assertEqual(diagnose.normalize_value("GE0/0/8"), "GigabitEthernet0/0/8")
        self.assertEqual(diagnose.normalize_value("XGE1/0/1"), "XGigabitEthernet1/0/1")

    def test_without_skills_behaves_as_before(self):
        reply = {"action": "answer", "clarify_question": "", "query": "怎么配置 trunk"}
        with mock.patch.object(config, "MOCK", False), mock.patch.object(qa, "chat", return_value=json.dumps(reply)) as chat:
            result = qa.dispatch("怎么配置 trunk")
        self.assertEqual(result["action"], "answer")
        self.assertEqual(chat.call_args.kwargs["schema"], qa.DISPATCH_SCHEMA)  # 原来的提示词和输出格式


    def test_answer_default_does_not_touch_skills_or_memory(self):
        """界面（ui/service.py）调用 answer() 不传 diagnose：不查技能、不读写记忆，返回字段和原来一样。"""
        reply = {"action": "greet", "clarify_question": "", "query": "你好"}
        with mock.patch.object(config, "MOCK", False), mock.patch.object(qa, "chat", return_value=json.dumps(reply)), \
                mock.patch.object(diagnose, "available_skills", side_effect=AssertionError("不应查技能")), \
                mock.patch.object(diagnose, "recall", side_effect=AssertionError("不应读记忆")):
            events = list(qa.answer_stream("你好"))
        self.assertEqual([e["event"] for e in events], ["dispatch", "final"])
        self.assertNotIn("suggestion", events[-1])


if __name__ == "__main__":
    unittest.main()
