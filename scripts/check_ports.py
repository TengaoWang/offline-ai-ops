"""Fail before startup if a loopback port is already owned by another process."""
import socket
import sys


errors = []
for raw in sys.argv[1:]:
    port = int(raw)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        errors.append(f"127.0.0.1:{port} 不可用：{exc}")
    finally:
        sock.close()
if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("端口检查通过：" + ", ".join(sys.argv[1:]))
