"""llm 接口测试。不需要 Ollama：检索部分用真实索引，问答和路由用 mock 模式。

运行：.venv/bin/python -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm import config, qa, rag, router  # noqa: E402
from tests.make_fixture import build  # noqa: E402


class RetrieveTest(unittest.TestCase):
    """只测 BM25 这一路（关闭向量模型），不需要 Ollama。"""

    @classmethod
    def setUpClass(cls):
        cls._embed_model = config.EMBED_MODEL
        config.EMBED_MODEL = ""
        cls.tmp = tempfile.TemporaryDirectory()
        docs = Path(cls.tmp.name) / "docs"
        build(docs / "测试手册.pdf")
        cls.index = Path(cls.tmp.name) / "index.db"
        cls.stats = rag.ingest(docs, cls.index)

    @classmethod
    def tearDownClass(cls):
        config.EMBED_MODEL = cls._embed_model
        cls.tmp.cleanup()

    def test_ingest_counts(self):
        self.assertEqual(self.stats["files"], 1)
        self.assertGreaterEqual(self.stats["chunks"], 3)

    def test_chinese_query_finds_right_page_and_section(self):
        top = rag.retrieve("接口被手动关闭怎么恢复", k=1, index_path=self.index)[0]
        self.assertEqual(top["page"], 3)
        self.assertEqual(top["section"], "2 故障处理 > 2.1 接口无法 Up")
        self.assertIn("undo shutdown", top["text"])

    def test_command_query(self):
        top = rag.retrieve("trunk allow-pass vlan", k=1, index_path=self.index)[0]
        self.assertEqual(top["page"], 1)

    def test_no_match_returns_empty(self):
        self.assertEqual(rag.retrieve("天气预报", k=3, index_path=self.index), [])

    def test_ask_with_no_results_has_full_shape(self):
        original = rag.retrieve
        rag.retrieve = lambda q, k=5: []
        try:
            result = rag.ask("天气预报")
        finally:
            rag.retrieve = original
        self.assertEqual(set(result), {"answer", "found", "citations", "unsupported_commands", "latency_s"})
        self.assertFalse(result["found"])

    def test_falls_back_to_bm25_without_vectors(self):
        top = rag.retrieve("trunk allow-pass vlan", k=1, index_path=self.index, mode="hybrid")[0]
        self.assertEqual(top["mode"], "bm25")
        self.assertIsNone(top["vec_score"])


class HybridTest(unittest.TestCase):
    """用假的向量模型测混合检索（RRF 合并），不需要 Ollama。"""

    @classmethod
    def setUpClass(cls):
        cls._embed_model, cls._embed = config.EMBED_MODEL, rag.embed
        config.EMBED_MODEL = "fake-embed"
        # 假向量：文本里含「恢复」的指向第一维，其余指向第二维
        rag.embed = lambda texts, model: [[1.0, 0.0] if "恢复" in t or "undo" in t else [0.0, 1.0] for t in texts]
        cls.tmp = tempfile.TemporaryDirectory()
        docs = Path(cls.tmp.name) / "docs"
        build(docs / "测试手册.pdf")
        cls.index = Path(cls.tmp.name) / "index.db"
        cls.stats = rag.ingest(docs, cls.index)

    @classmethod
    def tearDownClass(cls):
        config.EMBED_MODEL, rag.embed = cls._embed_model, cls._embed
        cls.tmp.cleanup()

    def test_vectors_built_for_every_chunk(self):
        self.assertEqual(self.stats["vectors"]["vectors"], self.stats["chunks"])

    def test_vector_finds_page_without_shared_keywords(self):
        top = rag.retrieve("恢复", k=1, index_path=self.index, mode="vector")[0]
        self.assertEqual(top["page"], 3)
        self.assertEqual(top["mode"], "vector")

    def test_hybrid_merges_both_rankings(self):
        results = rag.retrieve("trunk 恢复", k=3, index_path=self.index, mode="hybrid")
        self.assertEqual(results[0]["mode"], "hybrid")
        self.assertEqual({r["page"] for r in results[:2]}, {1, 3})
        self.assertIn("label", results[0])


class SectionChunkTest(unittest.TestCase):
    """按章节切块：去掉每页底部的页眉页脚；小节在页面中间开始时，按标题所在行分界。"""

    def test_footer_removed_and_mid_page_section_split(self):
        import pymupdf

        doc = pymupdf.open()
        bodies = ["第一章正文内容，介绍设备。", "继续第一章的内容。",
                  "第一章最后一段话。\n1.2 接口配置\n接口配置的说明。", "接口配置的更多说明。"]
        for n, body in enumerate(bodies, start=1):
            page = doc.new_page()
            page.insert_text((50, 72), body, fontname="china-s", fontsize=11)
            page.insert_text((50, 760), f"测试手册\n1 设备介绍\n版权所有\n{n}", fontname="china-s", fontsize=9)
        doc.set_toc([[1, "1 设备介绍", 1], [2, "1.1 概述", 1], [2, "1.2 接口配置", 3]])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "手册.pdf"
            doc.save(path)
            sections = {name: lines for name, lines in rag._pdf_sections(path)}
        overview = [line for _, line in sections["1 设备介绍 > 1.1 概述"]]
        interface = sections["1 设备介绍 > 1.2 接口配置"]
        self.assertIn("第一章最后一段话。", overview)
        self.assertNotIn("版权所有", overview)
        self.assertNotIn("3", overview)
        self.assertEqual(interface[0], (3, "1.2 接口配置"))
        self.assertEqual(interface[-1], (4, "接口配置的更多说明。"))


class NeighborTest(unittest.TestCase):
    """ask() 交给模型的资料：命中段 + 同一小节的前后相邻段，相邻的合并，重叠的行只保留一次。"""

    def test_join_overlapping_lines_once(self):
        self.assertEqual(rag._join_overlapping(["a\nb\nc", "b\nc\nd", "e"]), "a\nb\nc\nd\ne")

    def test_neighbors_same_section_only_and_merged(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.db"
            db = sqlite3.connect(index)
            db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, file TEXT, page INTEGER, section TEXT, text TEXT)")
            rows = [(1, "m.pdf", 9, "其他小节", "无关"), (2, "m.pdf", 10, "配置示例", "配置 A"),
                    (3, "m.pdf", 10, "配置示例", "配置 B"), (4, "m.pdf", 11, "配置示例", "查看结果"),
                    (5, "m.pdf", 12, "下一小节", "无关")]
            db.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)", rows)
            db.commit()
            db.close()
            hits = [{"id": i, "file": "m.pdf", "page": p, "section": s, "text": t} for i, _, p, s, t in rows]
            passages = rag._with_neighbors([hits[3], hits[1]], index)  # 命中「查看结果」和「配置 A」
        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0]["ids"], [2, 3, 4])
        self.assertEqual(passages[0]["text"], "配置 A\n配置 B\n查看结果")
        self.assertEqual(passages[0]["page"], 10)


class MockModeTest(unittest.TestCase):
    def setUp(self):
        self._mock = config.MOCK
        config.MOCK = True

    def tearDown(self):
        config.MOCK = self._mock

    def test_route_returns_known_skill_or_none(self):
        self.assertEqual(router.route("df -h 看到 /var 满了")["skill"], "disk-full")
        self.assertEqual(router.route("MES 服务器业务网不通，管理口能 ping 通")["skill"], "net-unreachable")
        self.assertIsNone(router.route("打印机卡纸了")["skill"])

    def test_ask_maps_citation_numbers_to_real_sources(self):
        result = rag.ask("接口不通")
        self.assertTrue(result["found"])
        self.assertEqual(result["citations"][0]["page"], 112)


class CitationGuardTest(unittest.TestCase):
    """模型给出不存在的编号、或没有任何出处时，必须判定为没找到依据。"""

    def _ask_with_reply(self, reply_json, source_text="x", other_text=None):
        original_chat, original_retrieve = rag.chat, rag.retrieve
        rag.chat = lambda *a, **kw: reply_json
        chunks = [{"id": 1, "text": source_text, "file": "a.pdf", "page": 1, "section": "s", "score": 1.0}]
        if other_text:
            chunks.append({"id": 2, "text": other_text, "file": "a.pdf", "page": 2, "section": "t", "score": 0.5})
        rag.retrieve = lambda q, k=5: chunks
        try:
            return rag.ask("问题")
        finally:
            rag.chat, rag.retrieve = original_chat, original_retrieve

    def test_invalid_citation_number_is_dropped(self):
        result = self._ask_with_reply('{"found": true, "answer": "编的", "citations": [7]}')
        self.assertFalse(result["found"])
        self.assertEqual(result["answer"], rag.NOT_FOUND)

    def test_answer_without_citation_is_not_found(self):
        result = self._ask_with_reply('{"found": true, "answer": "没引用", "citations": []}')
        self.assertFalse(result["found"])

    def test_command_not_in_source_is_rejected(self):
        source = "[SwitchB-GigabitEthernet0/0/1] port link-type trunk"
        reply = '{"found": true, "answer": "1. port link-type trunk\\n2. interface eth-trunk 1", "citations": [1]}'
        result = self._ask_with_reply(reply, source)
        self.assertFalse(result["found"])
        self.assertEqual(result["unsupported_commands"], ["interface eth-trunk 1"])

    def test_command_with_different_numbers_is_supported(self):
        source = "[SwitchB] interface GigabitEthernet 0/0/1\n[SwitchB-GigabitEthernet0/0/1] port link-type trunk"
        reply = ('{"found": true, "answer": "1. [Switch] interface GigabitEthernet 0/0/5\\n'
                 '2. port link-type trunk", "citations": [1]}')
        result = self._ask_with_reply(reply, source)
        self.assertTrue(result["found"])
        self.assertEqual(result["unsupported_commands"], [])

    def test_commands_next_to_chinese_are_extracted(self):
        self.assertEqual(rag._commands("执行display cpu-usage命令，再执行命令undo shutdown恢复"),
                         ["display cpu-usage", "undo shutdown"])

    def test_wrong_citation_number_is_corrected(self):
        reply = '{"found": true, "answer": "<HUAWEI> display saved-configuration", "citations": [1]}'
        result = self._ask_with_reply(reply, "无关内容", other_text="<HUAWEI> display saved-configuration")
        self.assertTrue(result["found"])
        self.assertEqual([c["n"] for c in result["citations"]], [1, 2])

    def test_device_output_is_not_treated_as_command(self):
        answer = ("<HUAWEI> save\nInfo: Please input the file name ( *.cfg, *.zip ) [vrpcfg.zip]:\n"
                  "flash:/vrpcfg.zip exists, overwrite?[Y/N]:y\nNow saving the current configuration.")
        self.assertEqual(rag._commands(answer), [])  # save 只有一个词，不检查；其余都是设备输出

    def test_valid_citation_kept(self):
        result = self._ask_with_reply('{"found": true, "answer": "见 [1]", "citations": [1]}')
        self.assertTrue(result["found"])
        self.assertEqual(result["citations"][0]["label"], "《a》 s P1")


class AnswerFlowTest(unittest.TestCase):
    """answer() 完整流程：调度器分流；模型回答通过核对就用它，没通过就退回手册原文。不需要 Ollama。"""

    PASSAGE = {"id": 1, "file": "a.pdf", "page": 7, "section": "配置 > trunk",
               "text": "步骤1 进入接口视图\ninterface GigabitEthernet 0/0/1\nport link-type trunk"}

    def setUp(self):
        self._saved = (qa.chat, qa.embed, rag.retrieve, rag.ask, rag._with_neighbors)
        rag.retrieve = lambda q, k=5: [self.PASSAGE]
        rag._with_neighbors = lambda chunks, index_path=None: [c | {"ids": [c["id"]]} for c in chunks]

    def tearDown(self):
        qa.chat, qa.embed, rag.retrieve, rag.ask, rag._with_neighbors = self._saved

    def _dispatch_to(self, action, clarify=""):
        qa.chat = lambda *a, **kw: f'{{"action": "{action}", "clarify_question": "{clarify}"}}'

    def test_greet_returns_intro_without_retrieval(self):
        self._dispatch_to("greet")
        rag.retrieve = lambda q, k=5: self.fail("打招呼不应该去检索")
        result = qa.answer("你是谁")
        self.assertEqual((result["action"], result["answer"]), ("greet", qa.INTRO))

    def test_english_locale_returns_english_intro(self):
        self._dispatch_to("greet")
        rag.retrieve = lambda q, k=5: self.fail("a greeting should not run retrieval")
        result = qa.answer("hello", locale="en")
        self.assertEqual((result["action"], result["answer"]), ("greet", qa.INTRO_EN))

    def test_reject_out_of_scope(self):
        self._dispatch_to("reject")
        self.assertEqual(qa.answer("Windows 怎么重装")["answer_type"], "out_of_scope")

    def test_clarify_returns_question(self):
        self._dispatch_to("clarify", "你想了解 S5700 的配置还是排障？")
        result = qa.answer("s5700")
        self.assertEqual((result["action"], result["answer"]), ("clarify", "你想了解 S5700 的配置还是排障？"))

    def test_clarify_without_question_falls_back_to_answer(self):
        self._dispatch_to("clarify", "")
        self.assertEqual(qa.dispatch("s5700")["action"], "answer")

    def test_bad_dispatch_output_is_protocol_error(self):
        qa.chat = lambda *a, **kw: "不是 JSON"
        with self.assertRaises(qa.LLMProtocolError):
            qa.dispatch("怎么配置 trunk")

    def test_generated_answer_used_when_verified(self):
        self._dispatch_to("answer")
        rag.ask = lambda q, prompt=None: {"found": True, "answer": "port link-type trunk", "citations": [{"n": 1}],
                             "unsupported_commands": []}
        result = qa.answer("怎么配置 trunk")
        self.assertEqual(result["answer_type"], "generated")

    def test_explicit_no_direct_answer_is_not_published_as_generated(self):
        self._dispatch_to("answer")
        rag.ask = lambda *a, **kw: {"found": True,
            "answer": "手册中没有直接回答这个问题，相关内容如下：", "citations": [{"n": 1}],
            "unsupported_commands": [], "latency_s": 0.1}
        result = qa.answer("直接告诉我是哪个端口")
        self.assertEqual(result["answer_type"], "not_found")
        self.assertEqual(result["citations"], [])

    def test_no_direct_disclaimer_with_sourced_details_is_retained(self):
        self._dispatch_to("answer")
        rag.ask = lambda *a, **kw: {"found": True,
            "answer": "手册中没有直接回答这个问题，相关内容如下：检查接口物理状态。", "citations": [{"n": 1}],
            "unsupported_commands": [], "latency_s": 0.1}
        result = qa.answer("接口状态")
        self.assertEqual(result["answer_type"], "generated")

    def test_unfinished_generated_lead_in_falls_back_to_source(self):
        self._dispatch_to("answer")
        rag.ask = lambda *a, **kw: {"found": True, "answer": "可按以下步骤检查：",
                                    "citations": [{"n": 1}], "unsupported_commands": [], "latency_s": 0.1}
        result = qa.answer("接口状态")
        self.assertEqual(result["answer_type"], "extracted")
        self.assertEqual(result["answer"], self.PASSAGE["text"])
        self.assertIn("port link-type trunk", result["extract"]["text"])

    def test_falls_back_to_source_text_when_not_verified(self):
        self._dispatch_to("answer")
        rag.ask = lambda q, prompt=None: {"found": False, "answer": rag.NOT_FOUND, "citations": [],
                             "unsupported_commands": ["interface eth-trunk 1"]}
        result = qa.answer("怎么配置 trunk")
        self.assertEqual(result["answer_type"], "extracted")
        self.assertEqual(result["answer"], self.PASSAGE["text"])
        self.assertEqual(result["citations"][0]["page"], 7)
        self.assertEqual(result["unsupported_commands"], ["interface eth-trunk 1"])

    def test_model_error_after_extract_propagates_as_system_error(self):
        self._dispatch_to("answer")

        def broken_ask(q, prompt=None):
            raise qa.LLMError("连不上 Ollama")
        rag.ask = broken_ask
        with self.assertRaises(qa.LLMError):
            qa.answer("怎么配置 trunk")

    def test_stream_gives_source_text_before_final(self):
        self._dispatch_to("answer")
        rag.ask = lambda q, prompt=None: {"found": False, "answer": rag.NOT_FOUND, "citations": [], "unsupported_commands": []}
        events = [e["event"] for e in qa.answer_stream("怎么配置 trunk")]
        self.assertEqual(events, ["dispatch", "extract", "final"])

    def test_follow_up_uses_rewritten_query_and_never_clarifies_twice(self):
        qa.chat = lambda *a, **kw: '{"action": "clarify", "clarify_question": "哪方面？", "query": "S5700 的型号规格"}'
        searched = []
        rag.retrieve = lambda q, k=5: searched.append(q) or [self.PASSAGE]
        rag.ask = lambda q, prompt=None: {"found": False, "answer": rag.NOT_FOUND, "citations": [], "unsupported_commands": []}
        history = [{"question": "s5700", "action": "clarify", "answer": "你想了解哪方面？"}]
        result = qa.answer("型号规格", history)
        self.assertEqual(result["action"], "answer")  # 上一轮已经追问过，不再追问
        self.assertEqual(result["query"], "S5700 的型号规格")
        self.assertEqual(searched, ["S5700 的型号规格"])

    def test_field_wording_for_clearing_configuration_expands_retrieval_query(self):
        self._dispatch_to("answer")
        seen = []
        rag.retrieve = lambda q, k=5: (seen.append(q) or [self.PASSAGE])
        rag.ask = lambda q, **kw: {"found": False, "answer": rag.NOT_FOUND, "citations": [],
                                  "unsupported_commands": [], "latency_s": 0.1}
        result = qa.answer("需要清空原有配置")
        self.assertIn("恢复出厂配置", result["query"])
        self.assertIn("恢复出厂配置", seen[0])

    def test_lost_admin_credential_expands_to_manual_terms(self):
        self._dispatch_to("answer")
        seen = []
        rag.retrieve = lambda q, k=5: (seen.append(q) or [self.PASSAGE])
        rag.ask = lambda q, **kw: {"found": False, "answer": rag.NOT_FOUND, "citations": [],
                                  "unsupported_commands": [], "latency_s": 0.1}
        result = qa.answer("S5700 管理员口令遗失但可用 Console 连接")
        self.assertIn("忘记登录密码", result["query"])
        self.assertIn("忘记登录密码", seen[0])

    def test_generic_lost_password_requires_model_and_access_context(self):
        self._dispatch_to("answer")
        rag.retrieve = lambda q, k=5: self.fail("条件不足时不应检索并发布某一型号的恢复步骤")
        result = qa.answer("管理员口令遗失且无法进入设备")
        self.assertEqual(result["answer_type"], "clarify")
        self.assertIn("设备型号", result["answer"])

    def test_citations_renumbered_in_order_of_appearance(self):
        citations = [{"n": 1, "label": "a"}, {"n": 3, "label": "c"}, {"n": 2, "label": "b"}]
        text, ordered = qa._renumber("第一点 [1]\n第二点 [3]\n第三点 [2]\n多余 [9]", citations)
        self.assertEqual(text, "第一点 [1]\n第二点 [2]\n第三点 [3]\n多余 ")
        self.assertEqual([(c["n"], c["label"]) for c in ordered], [(1, "a"), (2, "c"), (3, "b")])

    def test_new_flow_uses_its_own_prompt_and_ask_default_unchanged(self):
        self._dispatch_to("answer")
        prompts = []
        rag.ask = lambda q, prompt=None: prompts.append(prompt) or {
            "found": False, "answer": rag.NOT_FOUND, "citations": [], "unsupported_commands": []}
        qa.answer("怎么配置 trunk")
        self.assertEqual(prompts, [qa.QA_ANSWER_PROMPT])
        self.assertNotEqual(qa.QA_ANSWER_PROMPT, rag.ANSWER_PROMPT)

    def test_english_locale_selects_english_answer_prompt(self):
        self._dispatch_to("answer")
        prompts = []
        rag.ask = lambda q, prompt=None: prompts.append(prompt) or {
            "found": False, "answer": rag.NOT_FOUND, "citations": [], "unsupported_commands": []}
        qa.answer("How do I configure a trunk?", locale="en")
        self.assertEqual(prompts, [qa.QA_ANSWER_PROMPT_EN])

    def test_history_is_optional(self):
        self._dispatch_to("greet")
        self.assertEqual(qa.answer("你好")["query"], "你好")

    def test_extract_keeps_lines_verbatim_around_best_line(self):
        qa.embed = lambda texts, model: [[1.0, 0.0]] + [[1.0, 0.0] if "trunk" in t else [0.0, 1.0] for t in texts[1:]]
        lines = [f"无关内容第{i}行" + "。" * 40 for i in range(20)]
        lines[12] = "port link-type trunk"
        passage = dict(self.PASSAGE, text="\n".join(lines))
        excerpt = qa.extract("trunk", passage)["text"].split("\n")
        self.assertEqual(excerpt[:2], [lines[11], lines[12]])  # 最相关的一行，往前带 1 行
        self.assertLessEqual(len("".join(excerpt)), qa.EXTRACT_CHARS)


if __name__ == "__main__":
    unittest.main()
