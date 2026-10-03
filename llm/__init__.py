"""离线运维助手的模型与知识库接口。队友只需要：

    from llm import route, retrieve, ask, answer, chat, health

ask() 是只查手册的问答；answer() 是完整流程（调度器 → 原文截取 + 模型生成 → 审核），见 llm/qa.py。

详细说明见 llm/README.md。
"""

from . import config
from .client import LLMError
from .client import chat as _chat
from .client import list_models
from .qa import answer, answer_stream
from .rag import NOT_FOUND, ask, ingest, retrieve
from .router import SKILLS, route

__all__ = ["route", "retrieve", "ask", "answer", "answer_stream", "chat", "ingest", "health", "SKILLS",
           "NOT_FOUND", "LLMError"]


def chat(messages: list[dict], schema: dict | None = None, think: bool = False,
         num_predict: int | None = None) -> str:
    """通用模型调用（例如规则树未覆盖时的「AI 补充推理」）。返回回复文本。

    messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
    schema:   传 JSON Schema 时，输出保证是符合该结构的 JSON 字符串
    think:    复杂推理时可设为 True（更慢）
    """
    if config.MOCK:
        return '{"mock": true}' if schema else "[MOCK] 这是模拟回复。"
    return _chat(messages, schema=schema, think=think, num_predict=num_predict)


def health() -> dict:
    """Runtime readiness, using the same immutable revision as retrieval."""
    from . import kb
    import sqlite3
    status = {"mock": config.MOCK, "ollama": False, "backend_ready": False,
              "embed_backend_ready": False, "model": False, "embed_model": False,
              "index": False, "chunks": 0, "vectors": 0, "index_revision": None,
              "model_name": config.MODEL, "manual_files": [], "errors": [],
              "backend": config.BACKEND, "embed_backend": config.EMBED_BACKEND}
    try:
        models = {m.removesuffix(":latest") for m in list_models("chat")}
        embed_models = {m.removesuffix(":latest") for m in list_models("embed")}
        status.update(backend_ready=True, embed_backend_ready=True,
                      ollama=config.BACKEND == "ollama",
                      model=config.MODEL.removesuffix(":latest") in models,
                      embed_model=bool(config.EMBED_MODEL) and config.EMBED_MODEL.removesuffix(":latest") in embed_models)
    except Exception as exc:
        status["errors"].append(str(exc))
    try:
        snapshot = kb.current()
        path = kb.default_index()
        status.update(index_path=str(path), docs_dir=str(snapshot["docs"] if snapshot else config.DOCS_DIR),
                      index_revision=snapshot["revision"] if snapshot else None,
                      manual_files=snapshot["manifest"]["files"] if snapshot else [
                          {"name": p.name, "size": p.stat().st_size} for p in config.DOCS_DIR.glob("*") if p.is_file() and p.suffix.lower() in {".pdf", ".md", ".txt"}])
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            status["chunks"] = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            db.execute("SELECT count(*) FROM fts").fetchone()
            status["index"] = status["chunks"] > 0
            try:
                status["vectors"] = db.execute("SELECT COUNT(*) FROM vectors WHERE model=?", (config.EMBED_MODEL,)).fetchone()[0]
            except sqlite3.OperationalError:
                pass
    except Exception as exc:
        status["errors"].append(str(exc))
    status["vector_ready"] = bool(status["index"] and status["embed_model"] and status["vectors"] == status["chunks"])
    status["rag_ready"] = bool(status["backend_ready"] and status["model"] and status["index"])
    status["retrieval_mode"] = config.RETRIEVE_MODE if status["vector_ready"] else "bm25"
    return status
