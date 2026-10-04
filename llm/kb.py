"""Immutable manual/index snapshots. Only current.json is replaced on publish."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from pathlib import Path

from . import config


class KBError(RuntimeError):
    def __init__(self, message, code="index_invalid", status=503):
        super().__init__(message)
        self.code, self.status = code, status


def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def contained(root, child):
    root, child = Path(root).resolve(), Path(child).resolve()
    if not child.is_relative_to(root) or child == root:
        raise KBError("知识库路径不合法", "invalid_path", 400)
    return child


def object_dir(root, category, identifier):
    prefix = "u" if category in ("staging", "quarantine") else "r"
    if not isinstance(identifier, str) or not re.fullmatch(prefix + r"-[0-9a-f]{32}", identifier):
        raise KBError("无效的知识库对象 ID", "invalid_id", 400)
    return contained(root, Path(root) / category / identifier)


def sync_dir(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def current(root=None):
    """One pointer read; never guess another revision if it is corrupt."""
    root = Path(root or config.KB_ROOT)
    pointer = root / "current.json"
    if not pointer.exists():
        return None
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
        revision = data["revision"]
        directory = object_dir(root, "revisions", revision)
        manifest_path = contained(directory, directory / "manifest.json")
        if digest(manifest_path) != data["manifest_sha256"]:
            raise ValueError("manifest digest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["revision"] != revision or manifest.get("complete") is not True:
            raise ValueError("revision incomplete")
        docs = contained(directory, directory / "docs")
        index = contained(directory, directory / "index.db")
        if not docs.is_dir() or not index.is_file() or not manifest["files"]:
            raise ValueError("missing assets")
        for item in manifest["files"]:
            file = contained(docs, docs / item["name"])
            if (not file.is_file() or file.stat().st_size != item["size"] or
                    digest(file) != item["sha256"]):
                raise ValueError("manual missing or changed")
        return {"revision": revision, "directory": directory, "docs": docs,
                "index": index, "manifest": manifest}
    except Exception as exc:
        raise KBError("知识库版本指针或发布文件损坏，请恢复备份；未自动切换其他版本") from exc


def default_index():
    # Explicit LLM_INDEX_PATH remains a supported isolated CLI/test override.
    if "LLM_INDEX_PATH" in os.environ:
        return config.INDEX_PATH
    snapshot = current()
    return snapshot["index"] if snapshot else config.INDEX_PATH


def assert_writable(index):
    """Published revisions are immutable, including when passed explicitly."""
    path = Path(index).resolve()
    manifest = path.parent / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text()).get("complete"):
        raise KBError("已发布版本不可原地改写，请通过手册入库创建新版本", "immutable_revision", 409)


def validate_file(path):
    import pymupdf
    if path.suffix.lower() not in {".pdf", ".md", ".txt"}:
        raise KBError("仅支持 PDF、Markdown、TXT", "invalid_file", 400)
    if not path.stat().st_size:
        raise KBError("文件为空", "invalid_file", 400)
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            if doc.needs_pass or not len(doc):
                raise KBError("PDF 加密或没有页面", "invalid_file", 400)
            if not any(page.get_text().strip() for page in doc):
                raise KBError("PDF 无可提取文字，MVP 不支持 OCR", "invalid_file", 400)
    else:
        if not path.read_text(encoding="utf-8").strip():
            raise KBError("手册没有可用文字", "invalid_file", 400)


def stage(filename, data, root=None):
    root = Path(root or config.KB_ROOT)
    if (not isinstance(filename, str) or len(filename) > 180 or
            filename in (".", "..") or re.search(r'[\\/\x00-\x1f]', filename)):
        raise KBError("不合法的文件名", "invalid_filename", 400)
    if len(data) > 100 * 1024 * 1024:
        raise KBError("单份手册不能超过 100 MB", "file_too_large", 400)
    identifier = "u-" + uuid.uuid4().hex
    directory = object_dir(root, "staging", identifier)
    directory.mkdir(parents=True)
    try:
        path = contained(directory, directory / filename)
        path.write_bytes(data)
        validate_file(path)
        metadata = {"upload_id": identifier, "name": filename, "size": len(data), "sha256": digest(path)}
        write_json(directory / "upload.json", metadata)
        return metadata
    except Exception as exc:
        quarantine(root, identifier, str(exc))
        if isinstance(exc, KBError):
            raise
        raise KBError(f"文件不能解析，已隔离：{exc}", "invalid_file", 400) from exc


def quarantine(root, identifier, reason):
    source = object_dir(root, "staging", identifier)
    if source.exists():
        dest = object_dir(root, "quarantine", identifier)
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.rename(dest)
        write_json(dest / "failure.json", {"reason": reason})


def check_base(base, root=None):
    if base is not None:
        object_dir(root or config.KB_ROOT, "revisions", base)
    snapshot = current(root)
    if base != (snapshot["revision"] if snapshot else None):
        raise KBError("知识库版本已变化，请刷新并重新确认提交", "stale_revision", 409)
    return snapshot


def validate_index(index, files, require_vectors=True):
    with sqlite3.connect(index.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise KBError("候选索引校验失败")
        counts = dict(db.execute("SELECT file, COUNT(*) FROM chunks GROUP BY file"))
        if set(counts) != set(files) or not all(counts.values()):
            raise KBError("部分手册没有有效片段，未发布")
        db.execute("SELECT count(*) FROM fts").fetchone()
        chunks = sum(counts.values())
        vectors = 0
        try:
            vectors = db.execute("SELECT COUNT(*) FROM vectors WHERE model=?", (config.EMBED_MODEL,)).fetchone()[0]
        except sqlite3.OperationalError:
            pass
        if require_vectors and (not config.EMBED_MODEL or vectors != chunks):
            raise KBError("向量生成不完整，保留原有知识库")
    return {"chunks": chunks, "vectors": vectors}


def publish(directory, manifest, base, root=None):
    root = Path(root or config.KB_ROOT)
    if os.name != "nt":
        for path in directory.rglob("*"):
            if path.is_file():
                with path.open("rb") as f:
                    os.fsync(f.fileno())
    manifest["complete"] = True
    write_json(directory / "manifest.json", manifest)
    sync_dir(directory / "docs")
    sync_dir(directory)
    check_base(base, root)
    pointer = {"revision": manifest["revision"], "manifest_sha256": digest(directory / "manifest.json")}
    temporary = root / (".current-" + uuid.uuid4().hex + ".json")
    try:
        write_json(temporary, pointer)
        # Validate the serialized pointer before the only publication mutation.
        if json.loads(temporary.read_text()) != pointer:
            raise KBError("临时版本指针校验失败")
        check_base(base, root)
        os.replace(temporary, root / "current.json")
        sync_dir(root)
    finally:
        temporary.unlink(missing_ok=True)


def build(upload_ids, base, replace_names=(), root=None, progress=None, initial_docs=None):
    """Caller holds the process operation lock. No mutation of live manuals/index."""
    from .rag import ingest
    root = Path(root or config.KB_ROOT)
    snapshot = check_base(base, root)
    uploads = []
    for identifier in upload_ids:
        directory = object_dir(root, "staging", identifier)
        try:
            meta = json.loads((directory / "upload.json").read_text())
            path = contained(directory, directory / meta["name"])
            if digest(path) != meta["sha256"]:
                raise ValueError("文件摘要变化")
            uploads.append((identifier, path))
        except Exception as exc:
            raise KBError("暂存手册不存在或已改变，请重新上传", "invalid_upload", 400) from exc
    names = [path.name for _, path in uploads]
    if len(set(names)) != len(names):
        raise KBError("一次任务包含重复文件名", "duplicate_filename", 400)
    existing = {x["name"] for x in snapshot["manifest"]["files"]} if snapshot else set()
    if (existing & set(names)) - set(replace_names):
        raise KBError("同名文件需明确确认替换", "replacement_required", 409)
    revision = "r-" + uuid.uuid4().hex
    directory = object_dir(root, "revisions", revision)
    docs = directory / "docs"
    docs.mkdir(parents=True)
    try:
        source_docs = snapshot["docs"] if snapshot else Path(initial_docs or config.DOCS_DIR)
        source_names = existing if snapshot else {p.name for p in source_docs.iterdir()
                                                 if p.is_file() and p.suffix.lower() in {".pdf", ".txt", ".md"}}
        for name in source_names - set(names):
            source = contained(source_docs, source_docs / name)
            shutil.copyfile(source, docs / name)
            if snapshot:
                expected = next(x["sha256"] for x in snapshot["manifest"]["files"] if x["name"] == name)
                if digest(docs / name) != expected:
                    raise KBError("已发布手册摘要校验失败，未构建新版本")
        for _, path in uploads:
            shutil.copyfile(path, docs / path.name)
        records = []
        for path in sorted(docs.iterdir()):
            validate_file(path)
            records.append({"name": path.name, "size": path.stat().st_size, "sha256": digest(path)})
        if progress:
            progress("解析手册并生成向量，期间暂停问答")
        stats = ingest(docs, directory / "index.db")
        checked = validate_index(directory / "index.db", [x["name"] for x in records])
        for item in records:
            if digest(docs / item["name"]) != item["sha256"]:
                raise KBError("构建期间手册发生变化，未发布")
        manifest = {"revision": revision, "files": records, "model": config.EMBED_MODEL,
                    "chunks": checked["chunks"], "vectors": checked["vectors"], "format": 1}
        if progress:
            progress("核验并发布手册与索引")
        publish(directory, manifest, base, root)
        for identifier, _ in uploads:
            shutil.rmtree(object_dir(root, "staging", identifier), ignore_errors=True)
        return {"revision": revision, "stats": stats}
    except Exception as exc:
        for identifier, _ in uploads:
            quarantine(root, identifier, str(exc))
        write_json(directory / "failure.json", {"reason": str(exc)})
        raise
