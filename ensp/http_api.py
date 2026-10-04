"""Small loopback HTTP/SSE adapter for frontend development (stdlib only)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .models import EnspError
from .service import EnspService

PREFIX = "/api/ensp/v1"
DEFAULT_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


def make_server(service: EnspService, port: int = 8766, origins=DEFAULT_ORIGINS):
    allowed_origins = set(origins)
    for origin in allowed_origins:
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("UI origins must be local HTTP origins without a path")

    class Handler(BaseHTTPRequestHandler):
        server_version = "EnspLocal/1.0"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, fmt, *args):
            pass

        def headers_for(self, status, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self.headers.get("Origin")
            if origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def reply(self, status, value):
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.headers_for(status, "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def guard(self):
            expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in expected:
                self.reply(403, {"error": {"code": "host_denied", "message": "Use the loopback API address."}})
                return False
            origin = self.headers.get("Origin")
            own_origins = {"http://" + host for host in expected}
            if origin and origin not in allowed_origins | own_origins:
                self.reply(403, {"error": {"code": "origin_denied", "message": "UI origin is not allowed."}})
                return False
            return True

        def do_OPTIONS(self):
            if not self.guard():
                return
            self.headers_for(204, "application/json")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def body(self):
            if self.headers.get("Transfer-Encoding"):
                raise EnspError("invalid_request", "Chunked requests are not supported.")
            if self.headers.get_content_type() != "application/json":
                raise EnspError("invalid_request", "Send Content-Type: application/json.")
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("body size")
                value = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError) as exc:
                raise EnspError("invalid_request", "Expected a JSON object of 1–4096 bytes.") from exc
            if not isinstance(value, dict):
                raise EnspError("invalid_request", "Expected a JSON object.")
            return value

        def dispatch(self):
            streaming = False
            try:
                if not self.guard():
                    return
                if self.command == "GET" and self.path == PREFIX + "/config":
                    self.reply(200, {"schema_version": "1.0", "mode": service.mode, "config": service.config.to_dict()})
                    return
                if self.command == "GET" and self.path == PREFIX + "/health":
                    self.reply(200, service.health())
                    return
                routes = {PREFIX + "/" + action + suffix: (action, bool(suffix))
                          for action in ("diagnose", "verify") for suffix in ("", "/stream")}
                if self.command != "POST" or self.path not in routes:
                    self.reply(404, {"error": {"code": "not_found", "message": "Unknown endpoint."}})
                    return
                action, wants_stream = routes[self.path]
                body = self.body()
                expected = {"before_run_id"} if action == "verify" else set()
                if set(body) != expected or (action == "verify" and (
                    not isinstance(body["before_run_id"], str) or not 1 <= len(body["before_run_id"]) <= 100
                )):
                    raise EnspError("invalid_request", "diagnose accepts {}; verify requires only before_run_id.")

                def emit(event):
                    nonlocal streaming
                    if not streaming:
                        self.headers_for(200, "text/event-stream; charset=utf-8")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        streaming = True
                        self.close_connection = True
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"event: {event['event']}\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()

                callback = emit if wants_stream else None
                report = service.verify(body["before_run_id"], callback) if action == "verify" else service.diagnose(callback)
                if not wants_stream:
                    self.reply(200, report)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                # Disconnect cancels collection at the next emitted event; the service releases its lock.
                self.close_connection = True
            except Exception as exc:
                if isinstance(exc, EnspError):
                    code, message = exc.code, str(exc)
                    status = {"busy": 409, "baseline_not_found": 404}.get(code, 400)
                else:
                    code, message, status = "internal_error", "Unexpected adapter error; inspect the local test run.", 500
                error = {"event": "error", "error": {"code": code, "message": message}}
                if streaming:
                    try:
                        emit(error)
                    except OSError:
                        pass
                else:
                    self.reply(status, error)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
