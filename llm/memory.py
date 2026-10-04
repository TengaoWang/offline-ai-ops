"""长期记忆：全部存在本机，不联网。

两类记忆：
    episode  排查记录：每次执行技能后自动保存（时间、问题、技能、结论、处理建议）
    fact     现场信息：例如「MES 服务器地址是 192.168.10.20」；可以带技能变量（var/value），
             下次执行该技能时自动填入

存储：
    kb/memory.db      SQLite，检索用（文字 + bge-m3 向量）
    kb/memory/*.md    每条记忆一个 Markdown 文件，可以直接打开查看、修改、删除；
                      下次启动时自动同步回数据库（改了文字会重新算向量，删了文件就删除这条记忆）
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

import numpy as np

from . import config
from .client import embed

MEMORY_DB = Path(os.environ.get("MEMORY_DB", config.ROOT / "kb" / "memory.db"))
MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", config.ROOT / "kb" / "memory"))
MIN_SCORE = 0.55  # 向量相似度低于这个值的记忆不算相关

_SCHEMA = """CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY, kind TEXT, text TEXT, data TEXT, skill TEXT,
    created REAL, updated REAL, vec BLOB)"""


def _connect() -> sqlite3.Connection:
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(MEMORY_DB)
    db.execute(_SCHEMA)
    return db


def _vector(text: str) -> bytes | None:
    """算向量；向量模型不可用（没启动 Ollama、mock 模式）时返回 None，检索退回关键词匹配。"""
    if config.MOCK or not config.EMBED_MODEL:
        return None
    try:
        v = np.asarray(embed([text], config.EMBED_MODEL)[0], dtype=np.float32)
    except Exception:
        return None
    return (v / (np.linalg.norm(v) or 1.0)).tobytes()


def _row(row) -> dict:
    id_, kind, text, data, skill, created, updated = row[:7]
    return {"id": id_, "kind": kind, "text": text, "data": json.loads(data or "{}"), "skill": skill,
            "created": created, "updated": updated}


# ---------------------------------------------------------------------------
# Markdown 文件（给人看、给人改）
# ---------------------------------------------------------------------------

def _file(memory_id: int, kind: str) -> Path:
    return MEMORY_DIR / f"{kind}-{memory_id:04d}.md"


def _write_file(memory: dict) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(memory["created"]))
    label = "排查记录" if memory["kind"] == "episode" else "现场信息"
    data = json.dumps(memory["data"], ensure_ascii=False)
    _file(memory["id"], memory["kind"]).write_text(
        f"---\nid: {memory['id']}\nkind: {memory['kind']}\nskill: {memory['skill'] or ''}\n"
        f"created: {when}\ndata: {data}\n---\n\n# {label}\n\n{memory['text']}\n", encoding="utf-8")
    _write_index()


def _write_index() -> None:
    lines = ["# 长期记忆", "", "每条记忆一个文件。可以直接修改或删除文件，下次启动时自动同步。", ""]
    for memory in list_memories():
        when = time.strftime("%m-%d %H:%M", time.localtime(memory["created"]))
        name = _file(memory["id"], memory["kind"]).name
        lines.append(f"- [{when}] [{memory['text'][:60]}]({name})")
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    (MEMORY_DIR / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_file(path: Path) -> tuple[dict, str] | None:
    match = re.match(r"---\n(.*?)\n---\n\n# [^\n]*\n\n(.*)", path.read_text(encoding="utf-8"), re.S)
    if not match:
        return None
    meta = dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)
    return meta, match.group(2).strip()


def sync_from_files() -> dict:
    """把人对 Markdown 文件的修改同步回数据库：文字改了就更新并重算向量，文件删了就删除记忆。"""
    if not MEMORY_DIR.exists():
        return {"updated": 0, "deleted": 0}
    updated = deleted = 0
    with _connect() as db:
        rows = db.execute("SELECT id, kind, text, data FROM memories").fetchall()
        for id_, kind, text, data in rows:
            path = _file(id_, kind)
            if not path.exists():
                db.execute("DELETE FROM memories WHERE id = ?", (id_,))
                deleted += 1
                continue
            parsed = _read_file(path)
            if parsed is None:
                continue
            meta, new_text = parsed
            new_data = meta.get("data", data)
            try:
                json.loads(new_data)
            except ValueError:
                new_data = data
            if new_text != text or json.loads(new_data) != json.loads(data or "{}"):
                db.execute("UPDATE memories SET text = ?, data = ?, updated = ?, vec = ? WHERE id = ?",
                           (new_text, new_data, time.time(), _vector(new_text), id_))
                updated += 1
    if updated or deleted:
        _write_index()
    return {"updated": updated, "deleted": deleted}


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------

def add(kind: str, text: str, data: dict | None = None, skill: str | None = None) -> dict:
    """新增一条记忆。现场信息（fact）如果和已有的同一变量重复，就更新那一条，不重复保存。"""
    data = data or {}
    now = time.time()
    with _connect() as db:
        existing = None
        if kind == "fact" and data.get("var"):
            for row in db.execute("SELECT id, kind, text, data, skill, created, updated FROM memories "
                                  "WHERE kind = 'fact' AND skill IS ?", (skill,)):
                memory = _row(row)
                if memory["data"].get("var") == data["var"] and memory["data"].get("name") == data.get("name"):
                    existing = memory
                    break
        if existing:
            db.execute("UPDATE memories SET text = ?, data = ?, updated = ?, vec = ? WHERE id = ?",
                       (text, json.dumps(data, ensure_ascii=False), now, _vector(text), existing["id"]))
            memory_id, created = existing["id"], existing["created"]
        else:
            cursor = db.execute("INSERT INTO memories (kind, text, data, skill, created, updated, vec) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (kind, text, json.dumps(data, ensure_ascii=False), skill, now, now, _vector(text)))
            memory_id, created = cursor.lastrowid, now
    memory = {"id": memory_id, "kind": kind, "text": text, "data": data, "skill": skill,
              "created": created, "updated": now}
    _write_file(memory)
    return memory


def forget(memory_id: int) -> bool:
    with _connect() as db:
        row = db.execute("SELECT kind FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return False
        db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    _file(memory_id, row[0]).unlink(missing_ok=True)
    _write_index()
    return True


def list_memories(kind: str | None = None) -> list[dict]:
    with _connect() as db:
        rows = db.execute("SELECT id, kind, text, data, skill, created, updated FROM memories "
                          + ("WHERE kind = ? " if kind else "") + "ORDER BY created DESC",
                          (kind,) if kind else ()).fetchall()
    return [_row(r) for r in rows]


def facts_for(skill: str) -> dict:
    """某个技能已记住的变量值，例如 {"target": "192.168.10.20"}（最新的优先）。"""
    values = {}
    for memory in list_memories("fact"):
        data = memory["data"]
        if data.get("var") and data.get("value") and memory["skill"] in (skill, None) and data["var"] not in values:
            values[data["var"]] = data["value"]
    return values


def search(query: str, k: int = 3, kind: str | None = None) -> list[dict]:
    """按意思检索相关记忆（bge-m3 向量）；向量不可用时按关键词匹配。返回带 score 的记忆。"""
    with _connect() as db:
        rows = db.execute("SELECT id, kind, text, data, skill, created, updated, vec FROM memories "
                          + ("WHERE kind = ?" if kind else ""), (kind,) if kind else ()).fetchall()
    if not rows:
        return []
    query_vec = _vector(query)
    scored = []
    for row in rows:
        memory = _row(row)
        if query_vec is not None and row[7] is not None:
            score = float(np.dot(np.frombuffer(query_vec, dtype=np.float32), np.frombuffer(row[7], dtype=np.float32)))
            if score < MIN_SCORE:
                continue
        else:  # 关键词：查询里的词（2 个字以上的中文片段、英文、数字）在记忆里出现的比例
            words = set(re.findall(r"[A-Za-z0-9.]{2,}|[一-鿿]{2}", query))
            if not words:
                continue
            score = sum(1 for w in words if w.lower() in memory["text"].lower()) / len(words)
            if score < 0.3:
                continue
        scored.append(memory | {"score": round(score, 3)})
    scored.sort(key=lambda m: (-m["score"], -m["created"]))
    return scored[:k]
