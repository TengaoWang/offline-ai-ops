import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class PackagingTests(unittest.TestCase):
    def test_launchers_are_offline_and_loopback_only(self):
        for name in ("start_macos.command", "start_windows.ps1"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8").lower()
            self.assertIn("127.0.0.1", text)
            for forbidden in ("curl ", "wget ", "pip install", "brew install", "winget ", "invoke-webrequest"):
                self.assertNotIn(forbidden, text)

    def test_port_check_detects_collision(self):
        import socket
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        try:
            port = listener.getsockname()[1]
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_ports.py"), str(port)],
                                    capture_output=True)
        finally:
            listener.close()
        self.assertNotEqual(result.returncode, 0)

    def test_verifier_accepts_valid_manifest_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            required = ["app/ui/server.py", "app/engine/skill_engine.py", "kb/current.json", "config/backend"]
            for name in required:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name, encoding="utf-8")
            files = []
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                files.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            (root / "SHA256SUMS.json").write_text(json.dumps({"files": files}), encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts" / "verify_portable.py"), str(root)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            (root / "config" / "backend").write_text("tampered", encoding="utf-8")
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_builds_llama_macos_package_from_explicit_local_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python_runtime = root / "python"
            backend_runtime = root / "backend"
            models = root / "models-source"
            kb = root / "kb-source"
            for path in (python_runtime / "bin" / "python3", backend_runtime / "llama-server",
                         models / "chat.gguf", models / "embed.gguf", kb / "current.json"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
            output = root / "portable"
            command = [sys.executable, str(ROOT / "scripts" / "build_portable.py"),
                       "--platform", "macos", "--backend", "llama.cpp",
                       "--python-runtime", str(python_runtime), "--backend-runtime", str(backend_runtime),
                       "--models", str(models), "--kb-root", str(kb), "--output", str(output)]
            result = subprocess.run(command, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            manifest = json.loads((output / "SHA256SUMS.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["network_downloads"])
            self.assertEqual((output / "config" / "backend").read_text().strip(), "llama.cpp")
            self.assertTrue((output / "app" / "scripts" / "check_ports.py").is_file())


if __name__ == "__main__":
    unittest.main()
