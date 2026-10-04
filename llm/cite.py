"""强制溯源（FR-7）：把技能里写的手册章节号，换成索引里真实的出处。

技能的 refs.yaml 只写章节号（如 "8.2"），不写页码；页码、章节标题、原文一律从手册索引里查。
查不到就返回空列表，由调用方显示「手册中未找到依据」，不编造。

    from llm import cite
    cite(sections=["8.2"], query="接口物理 DOWN")
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import config, kb
from .rag import _cite_label, retrieve

EXCERPT_CHARS = 300


def _find_section(db, number: str) -> dict | None:
    """找章节路径里某一级正好是「number 标题」的段落，取该小节最靠前的一段。

    "8.2" 只匹配「8.2 接口物理DOWN…」这一级，不会匹配 8.20、8.21 或 18.2。"""
    pattern = re.compile(rf"(?:^| > ){re.escape(number)} ")
    like = f"%{number} %"
    # 按 id 顺序，第一条匹配的就是该章节最靠前的一段（页码最小）
    for chunk_id, file, page, section, text in db.execute(
            "SELECT id, file, page, section, text FROM chunks WHERE section LIKE ? ORDER BY id", (like,)):
        match = pattern.search(section or "")
        if match:
            # 截到匹配的那一级：出处显示到这个章节为止
            end = section.find(" > ", match.end())
            heading = section if end < 0 else section[:end]
            return {"id": chunk_id, "file": file, "page": page, "section": heading, "text": text}
    return None


def _source(chunk: dict, via: str) -> dict:
    return {"label": _cite_label(chunk), "file": Path(chunk["file"]).name, "page": chunk.get("page"),
            "section": chunk.get("section"), "text": (chunk.get("text") or "")[:EXCERPT_CHARS], "via": via}


def cite(sections: list[str] | tuple[str, ...] = (), query: str | None = None,
         index_path: Path | str | None = None) -> list[dict]:
    """章节号 → 真实出处。返回 [{"label", "file", "page", "section", "text", "via"}]。

    via：section（按章节号查到）/ search（章节号都没找到，按 query 检索到的第一段）。
    两种方式都找不到时返回 []。"""
    # Always follow the immutable, currently published knowledge-base revision.
    # config.INDEX_PATH is only the legacy location and can point at a stale copy.
    path = Path(index_path) if index_path else kb.default_index()
    results: list[dict] = []
    if path.exists():
        with sqlite3.connect(path) as db:
            for number in sections:
                chunk = _find_section(db, str(number).strip())
                if chunk and all(r["label"] != _cite_label(chunk) for r in results):
                    results.append(_source(chunk, "section"))
    if not results and query and path.exists():
        hits = retrieve(query, k=1, index_path=path)
        if hits:
            results.append(_source(hits[0], "search"))
    return results


def missing_sections(sections: list[str], index_path: Path | str | None = None) -> list[str]:
    """返回索引里找不到的章节号（启动时检查 refs.yaml 用）。"""
    path = Path(index_path) if index_path else kb.default_index()
    if not path.exists():
        return list(sections)
    with sqlite3.connect(path) as db:
        return [s for s in sections if _find_section(db, str(s).strip()) is None]
