"""python -m ensp: independently runnable connector, JSON output, optional SSE server."""

import argparse
import json
import sys
from pathlib import Path

from .fixtures import SCENARIOS, fixture_factory
from .http_api import DEFAULT_ORIGINS, make_server
from .models import EnspError, LabConfig
from .service import EnspService

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "labs" / "ensp-port-down" / "config.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local eNSP diagnostics; no Ollama/RAG dependency")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fixture", choices=SCENARIOS, help="Explicit synthetic data; never used as live fallback")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("health", "diagnose", "verify"):
        command = sub.add_parser(action)
        command.add_argument("--output", type=Path, help="Also save UTF-8 JSON to this path")
        if action == "verify":
            command.add_argument("--before", type=Path, required=True, help="Previously saved diagnosis JSON")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--allow-origin", action="append", help="Additional local UI origin, e.g. http://localhost:3000")
    args = parser.parse_args(argv)
    try:
        config = LabConfig.load(args.config)
        kwargs = {"mode": "fixture", "session_factory": fixture_factory(config, args.fixture)} if args.fixture else {}
        service = EnspService(config, **kwargs)
        if args.action == "serve":
            with make_server(service, args.port, (*DEFAULT_ORIGINS, *(args.allow_origin or []))) as server:
                print(f"eNSP API: http://127.0.0.1:{server.server_port}/api/ensp/v1 | mode={service.mode}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
            return 0
        if args.action == "health":
            result = service.health()
        elif args.action == "verify":
            before = json.loads(args.before.read_text(encoding="utf-8-sig"))
            result = service.diagnose(before=before)
        else:
            result = service.diagnose()
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
        print(output)
        passed = result.get("ready") if args.action == "health" else result["verification"]["passed"]
        return 0 if passed is True else 2
    except (EnspError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"error": {"code": getattr(exc, "code", "invalid_input"), "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
