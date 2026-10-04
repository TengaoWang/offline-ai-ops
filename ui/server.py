"""Local HTTP server for the offline AI ops frontend.

The server intentionally uses only the Python standard library plus the
existing llm package so it can run from the portable box without a frontend
toolchain or CDN access.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sqlite3
import urllib.parse
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from llm import config, health
from llm import kb
from llm.client import LLMError, LLMTimeout, LLMProtocolError
from .service import operations, APIError

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "ui" / "static"


def _json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _fallback_title(text: str, skill_id: str | None, locale: str) -> str:
    english = locale == "en"
    is_mes = bool(re.search(r"mes", text, re.I))
    titles = {
        "net-unreachable": ("MES network connectivity issue" if is_mes else "Network connectivity issue", "MES 业务网连通异常" if is_mes else "网络连通异常"),
        "disk-full": ("Switch storage alert", "交换机存储空间告警"),
        "service-down": ("Switch login failure", "交换机登录故障"),
        "log-audit": ("Log audit · suspicious activity", "日志审计 · 异常活动"),
    }
    if skill_id in titles:
        return titles[skill_id][0 if english else 1]
    cleaned = re.sub(r"^(一键体检[:：]|run selected skill[:：])", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned)
    limit = 52 if english else 24
    return (cleaned[:limit].rstrip("，。；;,. ") + ("…" if len(cleaned) > limit else "")) or ("New troubleshooting chat" if english else "新的排障会话")


def _make_title(text: str, skill_id: str | None, locale: str) -> tuple[str, str]:
    return _fallback_title(text, skill_id, locale), "local"


def list_skill_cards() -> list[dict[str, Any]]:
    return operations.list_skills()


def index_samples(limit: int = 3) -> list[dict[str, Any]]:
    if not kb.default_index().exists():
        return []
    with sqlite3.connect(kb.default_index().resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT file, page, section, text FROM chunks ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "file": file,
            "page": page,
            "section": section,
            "text": text[:360],
        }
        for file, page, section, text in rows
    ]


def extended_health() -> dict[str, Any]:
    skills = list_skill_cards()
    valid = [skill for skill in skills if skill.get("valid")]
    return health() | operations.status() | {
        "skills_count": len(skills), "valid_skills_count": len(valid),
        "invalid_skills_count": len(skills) - len(valid),
        "executor_ready": True, "engine_ready": len(valid) >= 4,
        "llm_backend": getattr(config, "BACKEND", "ollama"),
    }


def parse_multipart(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    message = BytesParser(policy=email_policy).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
    if not message.is_multipart():
        return []
    return [(part.get_filename(), part.get_payload(decode=True)) for part in message.iter_parts()
            if part.get_filename() is not None]


class UIHandler(BaseHTTPRequestHandler):
    server_version = "OfflineAIOpsUI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[ui] {self.address_string()} - {fmt % args}")

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = _json(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self, limit=128 * 1024):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise APIError("Content-Length 无效") from exc
        if length < 0 or length > limit:
            raise APIError("请求体过大或长度无效")
        self.connection.settimeout(30)
        body = self.rfile.read(length)
        self.connection.settimeout(None)
        if len(body) != length:
            raise APIError("请求内容不完整")
        return body

    def _read_json_body(self) -> dict[str, Any]:
        try:
            data = json.loads(self._read_body().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise APIError("请求必须是合法 JSON") from exc
        if not isinstance(data, dict):
            raise APIError("请求必须是 JSON 对象")
        return data

    def _failure(self, exc):
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        status = getattr(exc, "status", 500)
        code = getattr(exc, "code", "internal_error")
        if isinstance(exc, LLMTimeout):
            status, code = 504, "model_timeout"
        elif isinstance(exc, LLMProtocolError):
            status, code = 502, "model_protocol_error"
        elif isinstance(exc, LLMError):
            status, code = 503, "model_unavailable"
        try:
            self._send_json({"error": str(exc), "code": code}, status=status)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._send_json(extended_health())
            elif parsed.path == "/api/skills":
                self._send_json({"skills": list_skill_cards()})
            elif parsed.path == "/api/manuals/samples":
                self._send_json({"samples": index_samples()})
            elif parsed.path == "/api/memory":
                self._send_json(operations.list_memories())
            elif parsed.path == "/api/state":
                self._send_json(operations.load_state())
            elif parsed.path.startswith("/api/manuals/jobs/"):
                self._send_json(operations.job(parsed.path.rsplit("/", 1)[-1]))
            elif parsed.path.startswith("/api/diagnose/runs/") and parsed.path.endswith("/events"):
                identifier = parsed.path.split("/")[4]
                after = int(urllib.parse.parse_qs(parsed.query).get("after", ["0"])[0])
                self._diagnosis_events(identifier, after)
            elif parsed.path.startswith("/api/diagnose/runs/"):
                self._send_json(operations.diagnosis_run(parsed.path.rsplit("/", 1)[-1]))
            elif parsed.path.startswith("/api/"):
                self._send_json({"error": "not_found"}, status=404)
            else:
                self._serve_static(parsed.path)
        except Exception as exc:
            self._failure(exc)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/route":
                self._send_json(operations.route(self._read_json_body()))
            elif parsed.path == "/api/title":
                payload = self._read_json_body()
                title, source = _make_title(str(payload.get("text", ""))[:2000], None,
                                           "en" if payload.get("locale") == "en" else "zh-CN")
                self._send_json({"title": title, "source": source})
            elif parsed.path == "/api/ask":
                self._send_json(operations.ask(self._read_json_body()))
            elif parsed.path == "/api/diagnose/runs":
                self._send_json(operations.start_diagnosis(self._read_json_body()), status=202)
            elif parsed.path == "/api/manuals/upload":
                self._handle_upload()
            elif parsed.path == "/api/manuals/ingest":
                self._send_json(operations.start_build(self._read_json_body()), status=202)
            elif parsed.path == "/api/simulator/check":
                self._send_json(operations.simulator_check(self._read_json_body()))
            elif parsed.path == "/api/state":
                self._send_json(operations.save_state(self._read_json_body()))
            elif parsed.path in {"/api/skills/save", "/api/save-skill"}:
                self._handle_save_skill()
            else:
                self._send_json({"error": "not_found"}, status=404)
        except Exception as exc:
            self._failure(exc)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path.startswith("/api/memory/"):
                self._send_json(operations.forget_memory(parsed.path.rsplit("/", 1)[-1]))
            else:
                self._send_json({"error": "not_found"}, status=404)
        except Exception as exc:
            self._failure(exc)

    def _serve_static(self, path: str) -> None:
        requested = urllib.parse.unquote(path)
        if requested == "/":
            requested = "/index.html"
        static_root = STATIC_DIR.resolve()
        target = (STATIC_DIR / requested.lstrip("/")).resolve()
        if not target.is_file() or static_root not in [target, *target.parents]:
            self._send_json({"error": "not_found"}, status=404)
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, event: str, data: Any) -> None:
        self.wfile.write(f"event: {event}\n".encode("utf-8"))
        self.wfile.write(b"data: ")
        self.wfile.write(_json(data))
        self.wfile.write(b"\n\n")
        self.wfile.flush()

    def _diagnosis_events(self, identifier: str, after: int = 0) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for item in operations.diagnosis_events(identifier, after):
                self._send_sse(item["event"], item["data"] | {"sequence": item["sequence"]})
        except BrokenPipeError:
            return
        finally:
            self.close_connection = True

    def _handle_upload(self) -> None:
        files = parse_multipart(self.headers.get("Content-Type", ""), self._read_body(101 * 1024 * 1024))
        if len(files) != 1:
            raise APIError("每次上传一份手册")
        filename, data = files[0]
        saved = kb.stage(filename, data)
        self._send_json({"ok": True, "saved": [saved], "upload_id": saved["upload_id"]})

    def _handle_save_skill(self) -> None:
        result = operations.save_skill(self._read_json_body())
        self._send_json({"ok": True, **result, "skills": list_skill_cards()})


def self_check() -> dict[str, Any]:
    files = ["index.html", "styles.css", "app.js"]
    missing = [name for name in files if not (STATIC_DIR / name).exists()]
    external_refs: list[str] = []
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    for name in files:
        path = STATIC_DIR / name
        if not path.exists():
            continue
        for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for match in re.finditer(r"(?:https?:)?//[^\s\"'<>]+", line):
                reference = match.group(0).rstrip(".,;)")
                parsed = urllib.parse.urlsplit(reference if reference.startswith("http") else "https:" + reference)
                if parsed.hostname not in local_hosts:
                    external_refs.append(f"{name}:{index}:{reference}")
    return {
        "ok": not missing and not external_refs,
        "missing": missing,
        "external_refs": external_refs,
        "skills": len(list_skill_cards()),
        "samples": len(index_samples()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline-ai-ops local web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="run static self-check and exit")
    args = parser.parse_args()
    if args.check:
        result = self_check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    server = ThreadingHTTPServer((args.host, args.port), UIHandler)
    print(f"offline-ai-ops UI running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
