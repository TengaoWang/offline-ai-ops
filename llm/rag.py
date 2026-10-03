"""手册检索与带出处的问答：BM25 关键词检索 + 向量检索，用 RRF 合并。

流程：
  ingest()   把 kb/docs/ 下的 PDF / Markdown / TXT 切成小段，记下文件名、页码、章节，
             用 jieba 分词后存进 SQLite FTS5 索引（kb/index.db）；
             向量模型可用时，再给每段算向量存进同一个文件
  retrieve() BM25 和向量各取前 20 段，按名次用 RRF 合并；向量不可用时只用 BM25
  ask()      把这几段编号 [1]..[k] 交给模型；模型只能引用编号，由程序映射回真实的
             文件名 / 页码 / 章节，所以出处不会被模型编造；找不到依据时明确说没找到
"""

import json
import logging
import re
import sqlite3
import sys
import time
import warnings
from pathlib import Path

import numpy as np

from . import config
from .client import LLMError, chat, embed

with warnings.catch_warnings():  # jieba 在 Python 3.12 下会打印无害的 SyntaxWarning
    warnings.simplefilter("ignore", SyntaxWarning)
    import jieba
jieba.setLogLevel(logging.WARNING)

NOT_FOUND = "手册中未找到依据。"
CHUNK_CHARS = 600     # 每段最多字符数
OVERLAP_CHARS = 100   # 相邻两段的重叠，避免一句话被切断后检索不到
HEADING_WEIGHT = 1.0  # 章节标题命中的权重（相对正文）；在维护宝典上试过 1/2/3，1 整体最好
CANDIDATES = 20       # 混合检索时，BM25 和向量各取多少段参与合并
RRF_K = 60            # RRF 公式 1/(RRF_K + 名次) 里的常数，60 是论文和业界的常用值
EMBED_BATCH = 32      # 建向量时每次送给模型的段数

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


def _is_toc(text: str) -> bool:
    """目录页（大量「标题......页码」的引导点）对回答没有帮助，还会挤占检索结果，跳过。"""
    stripped = text.replace(" ", "")
    return len(stripped) > 0 and stripped.count(".") / len(stripped) > 0.3


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
    # 两列：heading = 最深两级章节标题，body = 正文；检索时标题命中的权重更高
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(heading, body)")

    count = 0
    for path in files:
        pages = _pdf_pages(path) if path.suffix.lower() == ".pdf" else _text_pages(path)
        for page, section, text in pages:
            if _is_toc(text):
                continue
            for piece in _split(text):
                cur = db.execute("INSERT INTO chunks (file, page, section, text) VALUES (?, ?, ?, ?)",
                                 (path.name, page, section, piece))
                heading = " ".join(section.split(" > ")[-2:])
                db.execute("INSERT INTO fts (rowid, heading, body) VALUES (?, ?, ?)",
                           (cur.lastrowid, _tokenize(heading), _tokenize(piece)))
                count += 1
    db.commit()
    db.close()
    stats = {"files": len(files), "chunks": count, "vectors": None}
    if config.EMBED_MODEL and not config.MOCK:
        try:
            stats["vectors"] = build_vectors(index_path=index_path)
        except LLMError as e:  # 没有向量模型也能用，只是退回 BM25
            stats["vectors"] = f"未生成：{e}"
    return stats


def _embed_text(section: str, text: str) -> str:
    """向量化时把章节标题放在正文前，标题里的关键词（如「接口物理DOWN」）也能被检索到。"""
    return f"{section}\n{text}" if section else text


def build_vectors(model: str | None = None, index_path: Path | str | None = None) -> dict:
    """给索引里的每一段算向量，存进 vectors 表。同一个索引可以存多个向量模型的结果。"""
    model = model or config.EMBED_MODEL
    index_path = Path(index_path or config.INDEX_PATH)
    start = time.perf_counter()
    db = sqlite3.connect(index_path)
    db.execute("CREATE TABLE IF NOT EXISTS vectors (model TEXT, id INTEGER, vec BLOB, PRIMARY KEY (model, id))")
    db.execute("DELETE FROM vectors WHERE model = ?", (model,))
    rows = db.execute("SELECT id, section, text FROM chunks ORDER BY id").fetchall()
    for i in range(0, len(rows), EMBED_BATCH):
        batch = rows[i:i + EMBED_BATCH]
        vectors = embed([_embed_text(section, text) for _, section, text in batch], model)
        db.executemany("INSERT INTO vectors (model, id, vec) VALUES (?, ?, ?)",
                       [(model, row[0], _normalize(v).tobytes()) for row, v in zip(batch, vectors)])
        done = i + len(batch)
        if done % (EMBED_BATCH * 20) == 0 or done == len(rows):
            print(f"\r向量化 {model}：{done}/{len(rows)}  {time.perf_counter() - start:.0f} 秒",
                  end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    db.commit()
    db.close()
    _VECTOR_CACHE.clear()
    return {"model": model, "vectors": len(rows), "seconds": round(time.perf_counter() - start, 1)}


def _normalize(vector) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


# ---------------------------------------------------------------------------
# 检索与问答
# ---------------------------------------------------------------------------

_MOCK_CHUNKS = [
    {"id": 1, "text": "[MOCK] port link-type trunk\nport trunk allow-pass vlan 10 20", "file": "mock_manual.pdf",
     "page": 52, "section": "VLAN 配置 > 配置接口链路类型", "score": 9.9},
    {"id": 2, "text": "[MOCK] display interface brief 查看接口状态", "file": "mock_manual.pdf",
     "page": 112, "section": "故障处理 > 接口无法 Up", "score": 7.5},
]


_VECTOR_CACHE: dict = {}


def _load_vectors(index_path: Path, model: str):
    """读出某个向量模型的全部向量，返回 (段 id 数组, 向量矩阵)；没有就返回 None。结果缓存在内存里。"""
    key = (str(index_path), model, index_path.stat().st_mtime)
    if key not in _VECTOR_CACHE:
        db = sqlite3.connect(index_path)
        try:
            rows = db.execute("SELECT id, vec FROM vectors WHERE model = ? ORDER BY id", (model,)).fetchall()
        except sqlite3.OperationalError:  # 旧索引没有 vectors 表
            rows = []
        db.close()
        _VECTOR_CACHE[key] = (np.array([r[0] for r in rows]),
                              np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])) if rows else None
    return _VECTOR_CACHE[key]


def _query_text(query: str, model: str) -> str:
    """Qwen3-Embedding 要求查询前加任务说明（文档片段不用加），效果更好。"""
    if "qwen3-embedding" in model:
        return f"Instruct: Given a question about network switch maintenance, retrieve manual passages that answer it\nQuery: {query}"
    return query


def _bm25_ranking(db, query: str, n: int) -> list[tuple[int, float]]:
    terms = [t for t in _tokenize(query).split() if len(t) > 1 or not t.isascii()]
    if not terms:
        return []
    match = " OR ".join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(terms))
    return db.execute(
        f"SELECT rowid, -bm25(fts, {HEADING_WEIGHT}, 1.0) AS score FROM fts WHERE fts MATCH ? "
        "ORDER BY score DESC LIMIT ?", (match, n)).fetchall()


def _vector_ranking(query: str, index_path: Path, n: int) -> list[tuple[int, float]] | None:
    """返回 [(段 id, 余弦相似度)]；向量模型或向量不可用时返回 None。"""
    model = config.EMBED_MODEL
    if not model:
        return None
    loaded = _load_vectors(index_path, model)
    if loaded is None:
        return None
    ids, matrix = loaded
    try:
        q = _normalize(embed([_query_text(query, model)], model)[0])
    except LLMError:
        return None
    sims = matrix @ q
    top = np.argsort(-sims)[:n]
    return [(int(ids[i]), float(sims[i])) for i in top]


def retrieve(query: str, k: int = 5, index_path: Path | str | None = None, mode: str | None = None) -> list[dict]:
    """返回最相关的 k 段：[{"id", "text", "file", "page", "section", "label", "score", "vec_score", "mode"}]。

    score 越大越相关（hybrid 为 RRF 分数，bm25 为 BM25 分数，vector 为余弦相似度）；
    vec_score 为向量余弦相似度（没有向量时为 None），可用来判断「手册里有没有相关内容」；
    mode 为实际使用的检索方式。page 为 None 表示来自没有页码的 Markdown / TXT 文件。
    """
    if config.MOCK:
        return [c | {"label": _cite_label(c), "vec_score": None, "mode": "mock"} for c in _MOCK_CHUNKS[:k]]
    index_path = Path(index_path or config.INDEX_PATH)
    if not index_path.exists():
        raise FileNotFoundError(f"索引不存在：{index_path}，请先运行 python -m llm ingest")
    mode = mode or config.RETRIEVE_MODE

    db = sqlite3.connect(index_path)
    vector = _vector_ranking(query, index_path, max(k, CANDIDATES)) if mode in ("hybrid", "vector") else None
    if vector is None:
        mode = "bm25"
    bm25 = _bm25_ranking(db, query, max(k, CANDIDATES)) if mode in ("hybrid", "bm25") else []

    vec_scores = dict(vector or [])
    if mode == "bm25":
        ranked = bm25[:k]
    elif mode == "vector":
        ranked = vector[:k]
    else:  # RRF：每一路里排第 r 名得 1/(RRF_K + r) 分，两路相加
        fused: dict[int, float] = {}
        for ranking in (bm25, vector):
            for rank, (chunk_id, _) in enumerate(ranking, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
        ranked = sorted(fused.items(), key=lambda x: -x[1])[:k]

    results = []
    for chunk_id, score in ranked:
        row = db.execute("SELECT id, text, file, page, section FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        chunk = dict(zip(["id", "text", "file", "page", "section"], row))
        vs = vec_scores.get(chunk_id)
        results.append(chunk | {"label": _cite_label(chunk), "score": round(score, 4),
                                "vec_score": round(vs, 4) if vs is not None else None, "mode": mode})
    db.close()
    return results


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
