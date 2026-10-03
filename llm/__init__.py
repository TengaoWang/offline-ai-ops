"""离线运维助手的模型与知识库接口。队友只需要：

    from llm import route, retrieve, ask, chat, health

详细说明见 llm/README.md。
"""

from . import config
from .client import LLMError
from .client import chat as _chat
from .client import list_models
from .rag import NOT_FOUND, ask, ingest, retrieve
from .router import SKILLS, route

__all__ = ["route", "retrieve", "ask", "chat", "ingest", "health", "SKILLS", "NOT_FOUND", "LLMError"]


def chat(messages: list[dict], schema: dict | None = None, think: bool = False) -> str:
    """通用模型调用（例如规则树未覆盖时的「AI 补充推理」）。返回回复文本。

    messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
    schema:   传 JSON Schema 时，输出保证是符合该结构的 JSON 字符串
    think:    复杂推理时可设为 True（更慢）
    """
    if config.MOCK:
        return '{"mock": true}' if schema else "[MOCK] 这是模拟回复。"
    return _chat(messages, schema=schema, think=think)


def health() -> dict:
    """检查各组件是否就绪：{"mock", "ollama", "model", "embed_model", "index", "chunks", "vectors"}。

    embed_model：向量模型是否已下载；vectors：索引里有多少段算好了向量。
    两者都正常时检索用 hybrid（BM25 + 向量），否则自动退回 BM25，效果会变差（口语问题尤其明显）。
    """
    status = {"mock": config.MOCK, "ollama": False, "model": False, "embed_model": False,
              "index": config.INDEX_PATH.exists(), "chunks": 0, "vectors": 0}
    try:
        models = list_models()
        status["ollama"] = True
        names = {m.removesuffix(":latest") for m in models}
        status["model"] = config.MODEL.removesuffix(":latest") in names
        status["embed_model"] = bool(config.EMBED_MODEL) and config.EMBED_MODEL.removesuffix(":latest") in names
    except Exception:
        pass
    if status["index"]:
        import sqlite3

        with sqlite3.connect(config.INDEX_PATH) as db:
            status["chunks"] = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            try:
                status["vectors"] = db.execute("SELECT COUNT(*) FROM vectors WHERE model = ?",
                                               (config.EMBED_MODEL,)).fetchone()[0]
            except sqlite3.OperationalError:  # 旧索引没有 vectors 表
                pass
    return status
