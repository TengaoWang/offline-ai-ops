"""llm 接口测试。不需要 Ollama：检索部分用真实索引，问答和路由用 mock 模式。

运行：.venv/bin/python -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm import config, rag, router  # noqa: E402
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


class MockModeTest(unittest.TestCase):
    def setUp(self):
        self._mock = config.MOCK
        config.MOCK = True

    def tearDown(self):
        config.MOCK = self._mock

    def test_route_returns_known_skill_or_none(self):
        self.assertEqual(router.route("df -h 看到 /var 满了")["skill"], "disk-full")
        self.assertIsNone(router.route("打印机卡纸了")["skill"])

    def test_ask_maps_citation_numbers_to_real_sources(self):
        result = rag.ask("接口不通")
        self.assertTrue(result["found"])
        self.assertEqual(result["citations"][0]["page"], 112)


class CitationGuardTest(unittest.TestCase):
    """模型给出不存在的编号、或没有任何出处时，必须判定为没找到依据。"""

    def _ask_with_reply(self, reply_json):
        original_chat, original_retrieve = rag.chat, rag.retrieve
        rag.chat = lambda *a, **kw: reply_json
        rag.retrieve = lambda q, k=5: [
            {"id": 1, "text": "x", "file": "a.pdf", "page": 1, "section": "s", "score": 1.0}]
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

    def test_valid_citation_kept(self):
        result = self._ask_with_reply('{"found": true, "answer": "见 [1]", "citations": [1]}')
        self.assertTrue(result["found"])
        self.assertEqual(result["citations"][0]["label"], "《a》 s P1")


if __name__ == "__main__":
    unittest.main()
