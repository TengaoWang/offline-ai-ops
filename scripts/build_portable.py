"""Assemble an offline package from explicitly supplied local runtime/model assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP_ITEMS = ("engine", "llm", "ui", "skills", "docs", "scripts", "requirements.txt", "README.md")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_tree(source: Path, target: Path):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))


def require(path: Path, description: str):
    if not path.exists():
        raise SystemExit(f"缺少{description}：{path}")


def main():
    parser = argparse.ArgumentParser(description="Build a no-download offline-ai-ops package")
    parser.add_argument("--platform", choices=("macos", "windows"), required=True)
    parser.add_argument("--backend", choices=("ollama", "llama.cpp"), required=True)
    parser.add_argument("--python-runtime", type=Path, required=True)
    parser.add_argument("--backend-runtime", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--kb-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("输出目录已存在；为防止覆盖，请使用一个新目录")
    for path, label in ((args.python_runtime, "便携 Python 运行时"), (args.backend_runtime, "模型后端运行时"),
                        (args.models, "离线模型目录"), (args.kb_root, "已发布知识库")):
        require(path, label)
    python_binary = args.python_runtime / ("python.exe" if args.platform == "windows" else "bin/python3")
    backend_binary = args.backend_runtime / (("ollama.exe" if args.platform == "windows" else "ollama") if args.backend == "ollama" else ("llama-server.exe" if args.platform == "windows" else "llama-server"))
    require(python_binary, "Python 可执行文件")
    require(backend_binary, "后端可执行文件")
    require(args.kb_root / "current.json", "知识库 current.json")
    if args.backend == "ollama":
        require(args.models / "manifests", "Ollama manifests")
        require(args.models / "blobs", "Ollama blobs")
    else:
        require(args.models / "chat.gguf", "聊天 GGUF")
        require(args.models / "embed.gguf", "向量 GGUF")
    args.output.mkdir(parents=True)
    app = args.output / "app"
    app.mkdir()
    for item in APP_ITEMS:
        source, target = ROOT / item, app / item
        copy_tree(source, target) if source.is_dir() else shutil.copy2(source, target)
    copy_tree(args.python_runtime, args.output / "runtime" / "python")
    copy_tree(args.backend_runtime, args.output / "backends" / args.backend)
    model_target = args.output / "models" / ("ollama" if args.backend == "ollama" else "")
    copy_tree(args.models, model_target)
    copy_tree(args.kb_root, args.output / "kb")
    (args.output / "config").mkdir()
    (args.output / "config" / "backend").write_text(args.backend + "\n", encoding="utf-8")
    launcher = "start_windows.cmd" if args.platform == "windows" else "start_macos.command"
    shutil.copy2(ROOT / "scripts" / launcher, args.output / launcher)
    if args.platform == "windows":
        shutil.copy2(ROOT / "scripts" / "start_windows.ps1", args.output / "start_windows.ps1")
    shutil.copy2(ROOT / "packaging" / "THIRD_PARTY_NOTICES.md", args.output / "THIRD_PARTY_NOTICES.md")
    files = []
    for path in sorted(p for p in args.output.rglob("*") if p.is_file()):
        files.append({"path": path.relative_to(args.output).as_posix(), "size": path.stat().st_size,
                      "sha256": sha256(path)})
    manifest = {"format": 1, "platform": args.platform, "backend": args.backend,
                "network_downloads": False, "files": files}
    (args.output / "SHA256SUMS.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "files": len(files), "backend": args.backend}, ensure_ascii=False))


if __name__ == "__main__":
    main()
