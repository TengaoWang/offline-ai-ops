"""手册检索与带出处的问答（简单版：BM25 关键词检索，未做向量检索和重排序）。

流程：
  ingest()   把 kb/docs/ 下的 PDF / Markdown / TXT 切成小段，记下文件名、页码、章节，
             用 jieba 分词后存进 SQLite FTS5 索引（kb/index.db）
  retrieve() 用 BM25 找出最相关的几段
  ask()      把这几段编号 [1]..[k] 交给模型；模型只能引用编号，由程序映射回真实的
             文件名 / 页码 / 章节，所以出处不会被模型编造；找不到依据时明确说没找到
"""

import json
import logging
import re
import sqlite3
import time
import warnings
from pathlib import Path

from . import config
from .client import chat

with warnings.catch_warnings():  # jieba 在 Python 3.12 下会打印无害的 SyntaxWarning
    warnings.simplefilter("ignore", SyntaxWarning)
    import jieba
jieba.setLogLevel(logging.WARNING)

NOT_FOUND = "手册中未找到依据。"
CHUNK_CHARS = 600     # 每段最多字符数
OVERLAP_CHARS = 100   # 相邻两段的重叠，避免一句话被切断后检索不到

ANSWER_PROMPT = """你是离线机房运维助手。只能根据下面带编号的手册片段回答用户问题。
规则：
1. 只使用片段里的内容，不要使用片段以外的知识，不要编造命令、参数、页码。
2. citations 填你实际用到的片段编号（整数）。
3. 片段不足以回答时，found 填 false，answer 填「手册中未找到依据。」，citations 为空。
4. 回答简洁，操作步骤用编号列出，命令原样保留。"""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["found", "answer", "citations"],
}

_PUNCT = re.compile(r"^[\W_]+$")


def _tokenize(text: str) -> str:
    """jieba 分词后用空格连接，供 FTS5 建索引和查询（FTS5 默认不会切分中文）。"""
    words = (w.strip().lower() for w in jieba.cut_for_search(text))
    return " ".join(w for w in words if w and not _PUNCT.match(w))


# ---------------------------------------------------------------------------
# 建索引
# ---------------------------------------------------------------------------

def _pdf_pages(path: Path):
    """逐页产出 (页码, 章节路径, 文本)。章节来自 PDF 书签（没有书签时为空）。"""
    import pymupdf

    doc = pymupdf.open(path)
    toc = doc.get_toc()  # [[层级, 标题, 起始页], ...]
    for index, page in enumerate(doc):
        page_no = index + 1
        trail = {}
        for level, title, start in toc:
            if start > page_no:
                break
            trail[level] = title.strip()
            for deeper in [k for k in trail if k > level]:
                del trail[deeper]
        yield page_no, " > ".join(trail[k] for k in sorted(trail)), page.get_text("text")


def _text_pages(path: Path):
    """Markdown / TXT：没有页码，按 # 标题记录章节。"""
    section, buffer = "", []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            if buffer:
                yield None, section, "\n".join(buffer)
                buffer = []
            section = line.lstrip("#").strip()
        else:
            buffer.append(line)
    if buffer:
        yield None, section, "\n".join(buffer)


def _split(text: str):
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= CHUNK_CHARS:
        if text:
            yield text
        return
    start = 0
    while start < len(text):
        yield text[start:start + CHUNK_CHARS]
        start += CHUNK_CHARS - OVERLAP_CHARS


def ingest(docs_dir: Path | str | None = None, index_path: Path | str | None = None) -> dict:
    """重建索引，返回 {"files": 文件数, "chunks": 片段数}。手册更新后重新运行即可。"""
    docs_dir = Path(docs_dir or config.DOCS_DIR)
    index_path = Path(index_path or config.INDEX_PATH)
    files = sorted(p for p in docs_dir.rglob("*") if p.suffix.lower() in {".pdf", ".md", ".txt"})
    if not files:
        raise FileNotFoundError(f"{docs_dir} 下没有 PDF / Markdown / TXT 文件")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.unlink(missing_ok=True)
    db = sqlite3.connect(index_path)
    db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, file TEXT, page INTEGER, section TEXT, text TEXT)")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(tokens)")

    count = 0
    for path in files:
        pages = _pdf_pages(path) if path.suffix.lower() == ".pdf" else _text_pages(path)
        for page, section, text in pages:
            for piece in _split(text):
                cur = db.execute("INSERT INTO chunks (file, page, section, text) VALUES (?, ?, ?, ?)",
                                 (path.name, page, section, piece))
                # 章节标题一起参与检索
                db.execute("INSERT INTO fts (rowid, tokens) VALUES (?, ?)",
                           (cur.lastrowid, _tokenize(f"{section}\n{piece}")))
                count += 1
    db.commit()
    db.close()
    return {"files": len(files), "chunks": count}


# ---------------------------------------------------------------------------
# 检索与问答
# ---------------------------------------------------------------------------

_MOCK_CHUNKS = [
    {"id": 1, "text": "[MOCK] port link-type trunk\nport trunk allow-pass vlan 10 20", "file": "mock_manual.pdf",
     "page": 52, "section": "VLAN 配置 > 配置接口链路类型", "score": 9.9},
    {"id": 2, "text": "[MOCK] display interface brief 查看接口状态", "file": "mock_manual.pdf",
     "page": 112, "section": "故障处理 > 接口无法 Up", "score": 7.5},
]


def retrieve(query: str, k: int = 5, index_path: Path | str | None = None) -> list[dict]:
    """返回最相关的 k 段：[{"id", "text", "file", "page", "section", "score"}]，score 越大越相关。

    page 为 None 表示来自没有页码的 Markdown / TXT 文件。
    """
    if config.MOCK:
        return _MOCK_CHUNKS[:k]
    index_path = Path(index_path or config.INDEX_PATH)
    if not index_path.exists():
        raise FileNotFoundError(f"索引不存在：{index_path}，请先运行 python -m llm ingest")
    terms = [t for t in _tokenize(query).split() if len(t) > 1 or not t.isascii()]
    if not terms:
        return []
    match = " OR ".join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(terms))
    db = sqlite3.connect(index_path)
    rows = db.execute(
        "SELECT c.id, c.text, c.file, c.page, c.section, -bm25(fts) AS score "
        "FROM fts JOIN chunks c ON c.id = fts.rowid WHERE fts MATCH ? ORDER BY score DESC LIMIT ?",
        (match, k),
    ).fetchall()
    db.close()
    keys = ["id", "text", "file", "page", "section", "score"]
    return [dict(zip(keys, row)) | {"score": round(row[5], 3)} for row in rows]


def _cite_label(chunk: dict) -> str:
    """渲染成「《文件名》章节 P页码」。"""
    parts = [f"《{Path(chunk['file']).stem}》"]
    if chunk.get("section"):
        parts.append(chunk["section"])
    if chunk.get("page"):
        parts.append(f"P{chunk['page']}")
    return " ".join(parts)


def ask(question: str, k: int = 5, model: str | None = None) -> dict:
    """根据手册回答问题。

    返回 {"answer": 回答, "found": 是否找到依据, "citations": [{"n", "file", "page", "section",
    "label", "text"}], "latency_s": 耗时}。found 为 False 时 answer 固定为「手册中未找到依据。」
    """
    start = time.perf_counter()
    chunks = retrieve(question, k=k)
    if not chunks:
        return {"answer": NOT_FOUND, "found": False, "citations": [], "latency_s": 0.0}

    if config.MOCK:
        reply = {"found": True, "answer": "[MOCK] 先用 display interface brief 查看接口状态 [2]。", "citations": [2]}
    else:
        context = "\n\n".join(f"[{i}] （{_cite_label(c)}）\n{c['text']}" for i, c in enumerate(chunks, 1))
        raw = chat(
            [{"role": "system", "content": ANSWER_PROMPT},
             {"role": "user", "content": f"手册片段：\n{context}\n\n问题：{question}"}],
            schema=ANSWER_SCHEMA,
            model=model,
        )
        try:
            reply = json.loads(raw)
        except json.JSONDecodeError:
            reply = {"found": False, "answer": NOT_FOUND, "citations": []}

    # 只保留真实存在的编号；没有任何有效出处的回答一律视为没找到依据
    numbers = [n for n in dict.fromkeys(reply.get("citations", [])) if isinstance(n, int) and 1 <= n <= len(chunks)]
    found = bool(reply.get("found")) and bool(numbers)
    citations = [
        {"n": n, "file": chunks[n - 1]["file"], "page": chunks[n - 1]["page"],
         "section": chunks[n - 1]["section"], "label": _cite_label(chunks[n - 1]), "text": chunks[n - 1]["text"]}
        for n in numbers
    ] if found else []
    return {
        "answer": reply.get("answer", NOT_FOUND) if found else NOT_FOUND,
        "found": found,
        "citations": citations,
        "latency_s": round(time.perf_counter() - start, 3),
    }
