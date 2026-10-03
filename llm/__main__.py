"""命令行：
  python -m llm health                 检查 Ollama、模型、索引
  python -m llm ingest [手册目录]       建立 / 重建手册索引（默认 kb/docs）
  python -m llm embed [向量模型]        给现有索引补算向量（默认 LLM_EMBED_MODEL）
  python -m llm route "nginx 起不来"    选技能包
  python -m llm search "trunk 配置"     只检索，不调用模型
  python -m llm ask "怎么配置 trunk"    带出处的问答
"""

import json
import sys

from . import ask, health, ingest, retrieve, route
from .rag import build_vectors


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"health", "ingest", "embed", "route", "search", "ask"}:
        sys.exit(__doc__)
    command, rest = sys.argv[1], " ".join(sys.argv[2:])
    if command == "health":
        result = health()
    elif command == "ingest":
        result = ingest(rest or None)
    elif command == "embed":
        result = build_vectors(rest or None)
    elif not rest:
        sys.exit(f'用法：python -m llm {command} "文本"')
    elif command == "route":
        result = route(rest)
    elif command == "search":
        result = retrieve(rest)
    else:
        result = ask(rest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
