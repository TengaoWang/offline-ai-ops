#!/bin/zsh
set -eu
PORTABLE_ROOT="${0:A:h}"
cd "$PORTABLE_ROOT/app"
mkdir -p "$PORTABLE_ROOT/logs" "$PORTABLE_ROOT/runtime-data"
BACKEND="$(tr -d '\r\n' < "$PORTABLE_ROOT/config/backend")"
PYTHON="$PORTABLE_ROOT/runtime/python/bin/python3"
export LLM_BACKEND="$BACKEND"
export LLM_EMBED_BACKEND="$BACKEND"
export LLM_KB_ROOT="$PORTABLE_ROOT/kb"
export PYTHONNOUSERSITE=1
PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM
if [[ "$BACKEND" == "ollama" ]]; then
  "$PYTHON" "$PORTABLE_ROOT/app/scripts/check_ports.py" 8765 11434
  export OLLAMA_HOST="127.0.0.1:11434"
  export OLLAMA_HOST_URL="http://127.0.0.1:11434"
  export OLLAMA_MODELS="$PORTABLE_ROOT/models/ollama"
  "$PORTABLE_ROOT/backends/ollama/ollama" serve >>"$PORTABLE_ROOT/logs/ollama.log" 2>&1 &
  PIDS+=("$!")
else
  "$PYTHON" "$PORTABLE_ROOT/app/scripts/check_ports.py" 8765 8080 8081
  export LLAMA_CPP_CHAT_HOST="http://127.0.0.1:8080"
  export LLAMA_CPP_EMBED_HOST="http://127.0.0.1:8081"
  "$PORTABLE_ROOT/backends/llama.cpp/llama-server" -m "$PORTABLE_ROOT/models/chat.gguf" --alias qwen3:4b --host 127.0.0.1 --port 8080 >>"$PORTABLE_ROOT/logs/llama-chat.log" 2>&1 &
  PIDS+=("$!")
  "$PORTABLE_ROOT/backends/llama.cpp/llama-server" -m "$PORTABLE_ROOT/models/embed.gguf" --alias bge-m3 --embedding --host 127.0.0.1 --port 8081 >>"$PORTABLE_ROOT/logs/llama-embed.log" 2>&1 &
  PIDS+=("$!")
fi
"$PYTHON" -m ui.server --host 127.0.0.1 --port 8765 >>"$PORTABLE_ROOT/logs/ui.log" 2>&1 &
PIDS+=("$!")
"$PYTHON" "$PORTABLE_ROOT/app/scripts/wait_ready.py" "http://127.0.0.1:8765"
wait "${PIDS[-1]}"
