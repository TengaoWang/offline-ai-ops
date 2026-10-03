"""手册检索与带出处的问答：BM25 关键词检索 + 向量检索，用 RRF 合并。

流程：
  ingest()   把 kb/docs/ 下的 PDF / Markdown / TXT 按书签切成小节、去掉页眉页脚，
             每节再切成不超过 600 字的段，记下文件名、起始页码、章节，
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
MIN_CHUNK_CHARS = 20  # 一节的最后一段太短（如只有标题）就不单独成段
FOOTER_LINES = 6      # 每页最后几行里找页眉页脚
TITLE_MATCH_CHARS = 12  # 用标题前多少个字（去掉空白）在正文里定位小节的起始行
HEADING_WEIGHT = 1.0  # 章节标题命中的权重（相对正文）；在维护宝典上试过 1/2/3，1 整体最好
CANDIDATES = 20       # 混合检索时，BM25 和向量各取多少段参与合并
RRF_K = 60            # RRF 公式 1/(RRF_K + 名次) 里的常数，60 是论文和业界的常用值
EMBED_BATCH = 32      # 建向量时每次送给模型的段数
ASK_PASSAGES = 3      # ask() 最多交给模型几段资料（每段 = 命中段 + 同一小节的前后相邻段）
NEIGHBORS = 1         # 命中一段时，前后各补几段（同一小节内）

ANSWER_PROMPT = """你是离线机房运维助手。只能根据下面带编号的手册片段回答用户问题。
规则：
1. 只使用片段里的内容，不要使用片段以外的知识。
2. 回答里的每一条命令都必须在片段里原样出现，逐字照抄；片段里没有的命令、参数、步骤一律不写。
3. 先判断片段讲的是不是用户问的那件事：名称相近但不是同一个功能或对象时，不能拿来回答。
4. citations 只填真正写着你所用内容的片段编号（整数）。
5. 片段不足以回答时，found 填 false，answer 填「手册中未找到依据。」，citations 为空。
6. 回答简洁，操作步骤用编号列出。"""

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

def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _pdf_lines(doc, toc) -> list[tuple[int, str]]:
    """全书正文的 [(页码, 行)]：跳过目录页，去掉每页底部的页眉页脚。

    维护宝典每页最后几行固定是「书名 / 章名 / 文档版本 / 版权 / 页码」，混在正文里是噪音。
    判断方法：页面最后 FOOTER_LINES 行中，在超过 30% 的页里重复出现的行、纯数字（页码）、
    或者等于某个一级章节标题的行，都当作页眉页脚删掉。
    """
    pages = [[line.strip() for line in page.get_text("text").splitlines() if line.strip()] for page in doc]
    tail_counts: dict[str, int] = {}
    for lines in pages:
        for line in set(lines[-FOOTER_LINES:]):
            key = re.sub(r"\d+", "#", _norm(line))
            tail_counts[key] = tail_counts.get(key, 0) + 1
    chapter_titles = {_norm(title) for level, title, _ in toc if level == 1}

    def is_footer(line: str) -> bool:
        key = _norm(line)
        return (key.isdigit() or key in chapter_titles
                or tail_counts.get(re.sub(r"\d+", "#", key), 0) > max(3, 0.3 * len(pages)))

    result = []
    for page_no, lines in enumerate(pages, start=1):
        if _is_toc("".join(lines)):
            continue
        cut = len(lines)
        while cut > 0 and len(lines) - cut < FOOTER_LINES and is_footer(lines[cut - 1]):
            cut -= 1
        result.extend((page_no, line) for line in lines[:cut])
    return result


def _pdf_sections(path: Path):
    """按书签把正文切成小节，产出 (章节路径, [(页码, 行), ...])。

    书签只给出每节的起始页，小节常在页面中间开始，所以在起始页（及下一页）里找标题所在的行作为分界。
    没有书签的 PDF 整本作为一节。
    """
    import pymupdf

    doc = pymupdf.open(path)
    toc = doc.get_toc()  # [[层级, 标题, 起始页], ...]
    lines = _pdf_lines(doc, toc)
    if not toc:
        yield "", lines
        return

    first_line_of_page: dict[int, int] = {}
    for i, (page_no, _) in enumerate(lines):
        first_line_of_page.setdefault(page_no, i)
    page_numbers = sorted(first_line_of_page)

    def page_start(page_no: int) -> int:  # 该页（或之后最近一页）的第一行
        for p in page_numbers:
            if p >= page_no:
                return first_line_of_page[p]
        return len(lines)

    starts, previous = [], 0
    for level, title, page_no in toc:
        key = _norm(title)[:TITLE_MATCH_CHARS]
        position = max(previous, page_start(page_no))
        search_end = page_start(page_no + 2)  # 标题在起始页或下一页
        for i in range(position, search_end):
            if _norm(lines[i][1]).startswith(key):
                position = i
                break
        starts.append((position, level, title.strip()))
        previous = position

    trail: dict[int, str] = {}
    for n, (position, level, title) in enumerate(starts):
        trail = {k: v for k, v in trail.items() if k < level} | {level: title}
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        if end - position > 1:  # 只有一行标题、没有正文的小节不单独成段
            yield " > ".join(trail[k] for k in sorted(trail)), lines[position:end]


def _text_sections(path: Path):
    """Markdown / TXT：没有页码，按 # 标题分节。"""
    section, buffer = "", []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            if buffer:
                yield section, buffer
                buffer = []
            section = line.lstrip("#").strip()
        elif line.strip():
            buffer.append((None, line.strip()))
    if buffer:
        yield section, buffer


def _is_toc(text: str) -> bool:
    """目录页（大量「标题......页码」的引导点）对回答没有帮助，还会挤占检索结果，跳过。"""
    stripped = text.replace(" ", "")
    return len(stripped) > 0 and stripped.count(".") / len(stripped) > 0.3


def _chunk_lines(lines: list[tuple[int | None, str]]):
    """把一节的行拼成不超过 CHUNK_CHARS 的段，只在行与行之间切开；
    相邻两段重叠末尾约 OVERLAP_CHARS 字的行。产出 (起始页码, 文本)。"""
    buffer: list[tuple[int | None, str]] = []
    size = 0
    for page, line in lines:
        while len(line) > CHUNK_CHARS:  # 极少数超长的行硬切
            lines_piece, line = line[:CHUNK_CHARS], line[CHUNK_CHARS:]
            if buffer:
                yield buffer[0][0], "\n".join(l for _, l in buffer)
                buffer, size = [], 0
            yield page, lines_piece
        if buffer and size + len(line) > CHUNK_CHARS:
            yield buffer[0][0], "\n".join(l for _, l in buffer)
            overlap: list[tuple[int | None, str]] = []
            for item in reversed(buffer):
                if sum(len(l) for _, l in overlap) + len(item[1]) > OVERLAP_CHARS:
                    break
                overlap.insert(0, item)
            buffer, size = overlap, sum(len(l) for _, l in overlap)
        buffer.append((page, line))
        size += len(line)
    if buffer and size >= MIN_CHUNK_CHARS:
        yield buffer[0][0], "\n".join(l for _, l in buffer)


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
    # 两列：heading = 完整章节路径（含章名），body = 正文
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(heading, body)")

    count = 0
    for path in files:
        sections = _pdf_sections(path) if path.suffix.lower() == ".pdf" else _text_sections(path)
        for section, lines in sections:
            for page, piece in _chunk_lines(lines):
                cur = db.execute("INSERT INTO chunks (file, page, section, text) VALUES (?, ?, ?, ?)",
                                 (path.name, page, section, piece))
                heading = section.replace(" > ", " ")
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
    """返回最相关的 k 段：[{"id", "text", "file", "page", "section", "label", "score", "vec_score",
    "bm25_rank", "vec_rank", "mode"}]，按 score 从高到低排，同一小节只保留分数最高的一段。

    score 越大越相关（hybrid 为 RRF 分数，bm25 为 BM25 分数，vector 为余弦相似度）；
    vec_score 为向量余弦相似度（没有向量时为 None），可用来判断「手册里有没有相关内容」；
    bm25_rank / vec_rank 为这一段在关键词 / 向量检索里各排第几（不在前 20 名时为 None）；
    mode 为实际使用的检索方式。page 为 None 表示来自没有页码的 Markdown / TXT 文件。
    """
    if config.MOCK:
        return [c | {"label": _cite_label(c), "vec_score": None, "bm25_rank": None, "vec_rank": None, "mode": "mock"}
                for c in _MOCK_CHUNKS[:k]]
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
    bm25_ranks = {chunk_id: rank for rank, (chunk_id, _) in enumerate(bm25, start=1)}
    vec_ranks = {chunk_id: rank for rank, (chunk_id, _) in enumerate(vector or [], start=1)}
    if mode == "bm25":
        ranked = bm25
    elif mode == "vector":
        ranked = vector
    else:  # RRF：每一路里排第 r 名得 1/(RRF_K + r) 分，两路相加
        fused: dict[int, float] = {}
        for ranking in (bm25, vector):
            for rank, (chunk_id, _) in enumerate(ranking, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
        ranked = sorted(fused.items(), key=lambda x: -x[1])

    # 同一小节只保留分数最高的一段，避免前几名被同一节占满（ask() 会再补上同一节的相邻段）
    results, seen_sections = [], set()
    for chunk_id, score in ranked:
        row = db.execute("SELECT id, text, file, page, section FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        chunk = dict(zip(["id", "text", "file", "page", "section"], row))
        if (chunk["file"], chunk["section"]) in seen_sections:
            continue
        seen_sections.add((chunk["file"], chunk["section"]))
        vs = vec_scores.get(chunk_id)
        results.append(chunk | {"label": _cite_label(chunk), "score": round(score, 4),
                                "vec_score": round(vs, 4) if vs is not None else None,
                                "bm25_rank": bm25_ranks.get(chunk_id), "vec_rank": vec_ranks.get(chunk_id),
                                "mode": mode})
        if len(results) == k:
            break
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


def _join_overlapping(texts: list[str]) -> str:
    """拼接相邻段：后一段开头和前一段末尾重叠的行只保留一次。"""
    lines: list[str] = []
    for text in texts:
        new = text.split("\n")
        overlap = next((n for n in range(min(len(lines), len(new)), 0, -1) if lines[-n:] == new[:n]), 0)
        lines.extend(new[overlap:])
    return "\n".join(lines)


def _with_neighbors(chunks: list[dict], index_path: Path | None = None) -> list[dict]:
    """把每个命中段扩展成「同一小节里的前后相邻段 + 命中段」，相邻或重叠的合并成一段。

    一个配置示例常被切成几段（如「配置 A」「配置 B」「查看结果」），只命中其中一段时，
    模型看不到完整的命令；补上相邻段可以解决。结果按命中名次排序。
    """
    index_path = Path(index_path or config.INDEX_PATH)
    if config.MOCK or not index_path.exists():
        return [c | {"ids": [c["id"]]} for c in chunks]
    db = sqlite3.connect(index_path)
    passages: list[dict] = []
    for chunk in chunks:
        rows = db.execute(
            "SELECT id, page, text FROM chunks WHERE file = ? AND section = ? AND id BETWEEN ? AND ? ORDER BY id",
            (chunk["file"], chunk["section"], chunk["id"] - NEIGHBORS, chunk["id"] + NEIGHBORS)).fetchall()
        ids = {r[0] for r in rows} | {chunk["id"]}
        for passage in passages:
            if passage["file"] == chunk["file"] and passage["section"] == chunk["section"] \
                    and min(ids) <= max(passage["ids"]) + 1 and max(ids) >= min(passage["ids"]) - 1:
                passage["ids"] = sorted(set(passage["ids"]) | ids)
                break
        else:
            passages.append(chunk | {"ids": sorted(ids)})
    for passage in passages:
        rows = db.execute(
            f"SELECT page, text FROM chunks WHERE file = ? AND section = ? "
            f"AND id IN ({','.join('?' * len(passage['ids']))}) ORDER BY id",
            [passage["file"], passage["section"], *passage["ids"]]).fetchall()
        if len(rows) == len(passage["ids"]):  # 段都在索引里才替换（防止和索引不一致的数据）
            passage["page"] = rows[0][0]
            passage["text"] = _join_overlapping([r[1] for r in rows])
    db.close()
    return passages


# 回答里的命令：小写字母开头的英文命令串（至少两个词，如 display interface brief），
# 或带连字符的单词命令（如 system-view）。行首的命令行提示符 [Switch-xxx] / <HUAWEI> 先去掉。
_PROMPT = re.compile(r"^\s*(?:\d+[.、)]\s*)?[\[<][^\]>]*[\]>]\s*")
# 用 (?<![A-Za-z0-9-]) 而不是 \b：中文字符也算 \w，「执行display cpu-usage命令」里的 \b 匹配不到
_COMMAND = re.compile(r"(?<![A-Za-z0-9-])(?:[a-z][a-z0-9-]*(?:[ \t]+[A-Za-z0-9][A-Za-z0-9/:.-]*)+"
                      r"|[a-z]+(?:-[a-z]+)+)(?![A-Za-z0-9-])")


def _command_key(text: str) -> str:
    """比较命令时忽略大小写、空白和具体数字（接口号、VLAN 号可以和手册示例不同）。"""
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", text.lower()))


# 设备的输出和提示（不是用户要敲的命令）：带 [Y/N] 的确认提示，或整行是以大写字母开头的英文，
# 如「Info: Please input the file name」「Now saving the current configuration」
_DEVICE_OUTPUT = re.compile(r"\[Y/N\]|^[A-Z][\x00-\x7f]*$")


def _commands(answer: str) -> list[str]:
    found = []
    for line in answer.splitlines():
        line = _PROMPT.sub("", line).strip()
        if _DEVICE_OUTPUT.search(line):
            continue
        for match in _COMMAND.finditer(line):
            command = match.group().strip()
            if command not in found:
                found.append(command)
    return found


def _unsupported_commands(answer: str, sources: list[str]) -> list[str]:
    """回答里在出处原文中找不到的命令。"""
    source_key = _command_key("\n".join(sources))
    return [c for c in _commands(answer) if _command_key(c) not in source_key]


def ask(question: str, k: int = 5, model: str | None = None) -> dict:
    """根据手册回答问题。

    返回 {"answer": 回答, "found": 是否找到依据, "citations": [{"n", "file", "page", "section",
    "label", "text"}], "unsupported_commands": 出处里找不到的命令, "latency_s": 耗时}。
    found 为 False 时 answer 固定为「手册中未找到依据。」。回答里的命令要能在出处原文中找到：
    标注的出处里没有、交给模型的其他资料里有，就把那一段补进出处；都找不到则判定为没有依据，
    那些命令放在 unsupported_commands 里，方便排查。
    """
    start = time.perf_counter()
    chunks = retrieve(question, k=k)
    if not chunks:
        return {"answer": NOT_FOUND, "found": False, "citations": [], "latency_s": 0.0}
    chunks = _with_neighbors(chunks)[:ASK_PASSAGES]

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
    # 回答里的每条命令都必须能在它引用的出处原文里找到，否则视为没有依据（防止拼凑、编造命令）
    answer = reply.get("answer", "")
    unsupported = _unsupported_commands(answer, [chunks[n - 1]["text"] for n in numbers]) if found else []
    # 命令在标注的出处里找不到、但在交给模型的其他资料里有：是模型标错了编号，把那一段补进出处
    for n, chunk in enumerate(chunks, 1):
        if unsupported and n not in numbers and len(_unsupported_commands("\n".join(unsupported), [chunk["text"]])) < len(unsupported):
            numbers.append(n)
            unsupported = _unsupported_commands(answer, [chunks[m - 1]["text"] for m in numbers])
    if unsupported:
        found = False
    citations = [
        {"n": n, "file": chunks[n - 1]["file"], "page": chunks[n - 1]["page"],
         "section": chunks[n - 1]["section"], "label": _cite_label(chunks[n - 1]), "text": chunks[n - 1]["text"]}
        for n in numbers
    ] if found else []
    return {
        "answer": reply.get("answer", NOT_FOUND) if found else NOT_FOUND,
        "found": found,
        "citations": citations,
        "unsupported_commands": unsupported,
        "latency_s": round(time.perf_counter() - start, 3),
    }
