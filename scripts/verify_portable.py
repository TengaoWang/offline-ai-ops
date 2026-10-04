"""Verify an assembled portable package without starting it."""
import hashlib
import json
import sys
from pathlib import Path


root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
manifest_path = root / "SHA256SUMS.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
errors = []
for item in manifest["files"]:
    path = (root / item["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        errors.append(f"缺失或越界：{item['path']}")
        continue
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != item["sha256"] or path.stat().st_size != item["size"]:
        errors.append(f"摘要或大小不一致：{item['path']}")
required = ["app/ui/server.py", "app/engine/skill_engine.py", "kb/current.json", "config/backend"]
errors += [f"缺少必要文件：{name}" for name in required if not (root / name).is_file()]
print(json.dumps({"ok": not errors, "errors": errors, "files": len(manifest["files"])}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 1)
