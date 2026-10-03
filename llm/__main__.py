"""命令行：
  python -m llm health                 检查 Ollama、模型、索引
  python -m llm ingest [手册目录]       建立 / 重建手册索引（默认 kb/docs）
  python -m llm embed [向量模型]        给现有索引补算向量（默认 LLM_EMBED_MODEL）
  python -m llm route "nginx 起不来"    选技能包
  python -m llm search "trunk 配置"     只检索，不调用模型
  python -m llm ask "怎么配置 trunk"    带出处的问答

search / ask 默认输出给人看的格式；加 --json 输出原始数据（和 Python 接口的返回值相同）。
"""

import json
import sys

from . import ask, health, ingest, retrieve, route
from .rag import _tokenize, build_vectors

PREVIEW_CHARS = 120  # search 结果每段预览多少字


def _short_label(item: dict) -> str:
    """出处只显示最后两级章节，完整路径太长。"""
    section = " > ".join(item["section"].split(" > ")[-2:]) if item.get("section") else ""
    page = f" P{item['page']}" if item.get("page") else ""
    return f"《{item['file'].rsplit('.', 1)[0]}》{section}{page}"


def _preview(query: str, text: str) -> str:
    """从和问题最相关的那一行开始预览（命中问题里词最多的行），而不是总从段落开头显示。"""
    terms = {t for t in _tokenize(query).split() if len(t) > 1}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    best = max(range(len(lines)), key=lambda i: sum(t in lines[i].lower() for t in terms))
    snippet = " ".join(" ".join(lines[best:]).split())
    prefix = "…" if best > 0 else ""
    return f"{prefix}{snippet[:PREVIEW_CHARS]}{'…' if len(snippet) > PREVIEW_CHARS else ''}"


def _print_search(query: str, results: list[dict]):
    print(f"问：{query}\n")
    if not results:
        print("没有找到相关内容。")
        return
    mode = results[0]["mode"]
    for n, r in enumerate(results, 1):
        found_by = []  # 这一段在两路检索里各排第几
        if r.get("bm25_rank"):
            found_by.append(f"关键词第 {r['bm25_rank']} 名")
        if r.get("vec_rank"):
            found_by.append(f"向量第 {r['vec_rank']} 名（相似度 {r['vec_score']:.3f}）")
        print(f"[{n}] 分数 {r['score']:.4f}  {_short_label(r)}")
        if found_by:
            print(f"    来自：{'，'.join(found_by)}")
        print(f"    {_preview(query, r['text'])}\n")
    print(f"检索方式：{mode}" + ("（分数 = 两路名次合并的 RRF 分数，从高到低排）" if mode == "hybrid" else ""))


def _print_ask(question: str, result: dict):
    print(f"问：{question}\n")
    print(f"答：\n{result['answer']}\n")
    if result["citations"]:
        print("出处：")
        for c in result["citations"]:
            print(f"  [{c['n']}] {_short_label(c)}")
        print()
    print(f"耗时 {result['latency_s']:.1f} 秒")


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    if not args or args[0] not in {"health", "ingest", "embed", "route", "search", "ask"}:
        sys.exit(__doc__)
    command, rest = args[0], " ".join(args[1:])
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
        if not as_json:
            return _print_search(rest, result)
    else:
        result = ask(rest)
        if not as_json:
            return _print_ask(rest, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
