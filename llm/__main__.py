"""命令行：
  python -m llm health                 检查 Ollama、模型、索引
  python -m llm ingest [手册目录]       建立 / 重建手册索引（默认 kb/docs）
  python -m llm embed [向量模型]        给现有索引补算向量（默认 LLM_EMBED_MODEL）
  python -m llm route "nginx 起不来"    选技能包
  python -m llm search "trunk 配置"     只检索，不调用模型
  python -m llm ask "怎么配置 trunk"    带出处的问答（只查手册）
  python -m llm answer "怎么配置 trunk" 完整流程：先判断问题类型，再给原文和整理后的回答
  python -m llm answer                 连续对话（记得上一轮，可以回答追问），直接回车退出

search / ask 默认输出给人看的格式；加 --json 输出原始数据（和 Python 接口的返回值相同）。
search 列出结果后，可以输入编号查看那一条的全文（含同一小节的前后段）；加 --full 一次显示全部全文。
"""

import json
import sys

from . import answer_stream, ask, health, ingest, retrieve, route
from .rag import _tokenize, _with_neighbors, build_vectors

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
    for n, r in enumerate(results, 1):
        print(f"[{n}] {_short_label(r)}")
        print(f"    {_preview(query, r['text'])}\n")
    print("按可能性从高到低排列（各项分数见 --json）")


def _print_full(result: dict):
    """显示一条结果的全文：命中段 + 同一小节的前后相邻段（和 ask() 交给模型的资料一样）。"""
    passage = _with_neighbors([result])[0]
    print(f"\n{'=' * 60}\n{_short_label(passage)}\n{passage['section']}\n{'=' * 60}")
    print(passage["text"])
    print("=" * 60)


def _browse(results: list[dict]):
    """列出结果后，输入编号看全文；直接回车退出。只在终端里交互使用时启用。"""
    while True:
        try:
            choice = input(f"\n输入编号（1-{len(results)}）查看全文，直接回车退出：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not choice:
            return
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            _print_full(results[int(choice) - 1])
        else:
            print("请输入列表里的编号。")


def _print_ask(question: str, result: dict):
    print(f"问：{question}\n")
    print(f"答：\n{result['answer']}\n")
    if result["citations"]:
        print("出处：")
        for c in result["citations"]:
            print(f"  [{c['n']}] {_short_label(c)}")
        print()
    print(f"耗时 {result['latency_s']:.1f} 秒")


_ANSWER_TITLES = {
    "generated": "答（已核对出处）：",
    "extracted": "模型没能给出有依据的回答，以下为手册原文，请自行判断：",
    "intro": "答：", "out_of_scope": "答：", "clarify": "需要再确认一下：", "not_found": "答：",
}


def _print_answer(question: str, as_json: bool, history: list[dict] | None = None) -> dict:
    """完整流程：原文先显示（约 1 秒），模型整理的回答随后显示。返回 answer() 的结果，供下一轮作为历史。"""
    if not as_json:
        print(f"问：{question}\n")
    result = {}
    for event in answer_stream(question, history):
        if event["event"] == "final":
            result = {k: v for k, v in event.items() if k != "event"}
        if event["event"] == "dispatch" and not as_json and event["query"] != question:
            print(f"（理解为：{event['query']}）\n", flush=True)
        if as_json:
            if event["event"] == "final":
                print(json.dumps({k: v for k, v in event.items() if k != "event"}, ensure_ascii=False, indent=2))
        elif event["event"] == "extract":
            excerpt = event["extract"]
            print(f"【手册原文】{_short_label(excerpt)}\n{excerpt['text']}\n", flush=True)
            print("模型正在整理回答……\n", flush=True)
        elif event["event"] == "final":
            if event["answer_type"] != "extracted":  # 退回原文时，原文上面已经显示过了
                print(f"{_ANSWER_TITLES[event['answer_type']]}\n{event['answer']}\n")
                for c in event["citations"]:
                    print(f"  出处 [{c['n']}] {_short_label(c)}")
            else:
                print(_ANSWER_TITLES["extracted"].rstrip("：") + "（见上方【手册原文】）")
                if event["unsupported_commands"]:
                    print(f"  原因：回答里的命令在手册中找不到 {event['unsupported_commands']}")
            print(f"\n耗时 {event['latency_s']:.1f} 秒")
    return result


def _chat_loop():
    """连续对话：每一轮都带上之前的结果，用户可以直接回答追问。"""
    history: list[dict] = []
    print("连续对话模式，直接回车退出。")
    while True:
        try:
            question = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not question:
            return
        history.append(_print_answer(question, False, history))


def main():
    args = [a for a in sys.argv[1:] if a not in ("--json", "--full")]
    as_json = "--json" in sys.argv[1:]
    full = "--full" in sys.argv[1:]
    if not args or args[0] not in {"health", "ingest", "embed", "route", "search", "ask", "answer"}:
        sys.exit(__doc__)
    command, rest = args[0], " ".join(args[1:])
    if command == "health":
        result = health()
    elif command == "ingest":
        result = ingest(rest or None)
    elif command == "embed":
        result = build_vectors(rest or None)
    elif command == "answer" and not rest:
        return _chat_loop()
    elif not rest:
        sys.exit(f'用法：python -m llm {command} "文本"')
    elif command == "route":
        result = route(rest)
    elif command == "search":
        result = retrieve(rest)
        if not as_json:
            _print_search(rest, result)
            if full:
                for r in result:
                    _print_full(r)
            elif result and sys.stdin.isatty() and sys.stdout.isatty():
                _browse(result)
            return
    elif command == "answer":
        return _print_answer(rest, as_json)
    else:
        result = ask(rest)
        if not as_json:
            return _print_ask(rest, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
