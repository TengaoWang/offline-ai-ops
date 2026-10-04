"""Wait for the bundled local UI, then open the system browser. Standard library only."""
import json
import sys
import time
import urllib.request
import webbrowser


url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
deadline = time.monotonic() + 180
last_error = ""
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=3) as response:
            health = json.loads(response.read())
        if health.get("rag_ready") and health.get("engine_ready"):
            webbrowser.open(url)
            raise SystemExit(0)
        last_error = "服务已启动但尚未就绪：" + "；".join(health.get("errors", []))
    except Exception as exc:
        last_error = str(exc)
    time.sleep(1)
print("启动超时（180秒）：" + last_error, file=sys.stderr)
raise SystemExit(1)
