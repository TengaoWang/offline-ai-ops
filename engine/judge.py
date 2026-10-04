"""混合判定（FR-5）：规则树没覆盖到的异常，交给模型推理，结论标注「AI 推理」。

rules.yaml 里用 ai_review 指定要复核的输出：

    ai_review:
      - cmd: logbuffer                        # 哪条命令的输出
        line: '%%\\d+\\w+/\\d/'               # 哪些行算「需要判断的记录」
        covered: ['ARP_DUPLICATE_IPADDR']     # 规则树已经处理的，不再交给模型

剩下的行交给模型。模型只能根据这些输出推理；出处由程序检索手册后给出编号让模型选，
选不出就是「手册中未找到依据」，不编造。模型不可用时返回 None，由调用方列为未完成项。
"""

from __future__ import annotations

import json
import re

from llm import LLMError, chat, config, retrieve
from llm.rag import _cite_label

MAX_LINES = 20
PASSAGES = 3

PROMPT = """你是交换机运维助手。下面是从交换机采集到的记录，规则库没有覆盖这些记录，需要你补充判断。
只根据给出的记录和手册片段推理，不要编造记录里没有的现象。

要求：
- severity：critical（严重，业务受影响）/ warning（需要关注）/ ok（正常，无需处理）
- title：一句话结论；symptom：引用记录里的关键内容；root_cause：可能的原因
- fix_commands：建议的排查或处理命令，优先用手册片段里出现的命令；会修改配置的命令只作为建议
- source：结论依据的手册片段编号（1-{n}），没有相关片段填 0
- summary：用两三句话说明你的判断过程"""

SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": ["critical", "warning", "ok"]},
        "title": {"type": "string"},
        "symptom": {"type": "string"},
        "root_cause": {"type": "string"},
        "fix_commands": {"type": "array", "items": {"type": "string"}},
        "source": {"type": "integer"},
        "summary": {"type": "string"},
    },
    "required": ["severity", "title", "symptom", "root_cause", "fix_commands", "source", "summary"],
}


def uncovered_lines(review: dict, raw: str) -> list[str]:
    """取出需要 AI 判断的行：符合 line、且不符合任何 covered 的行。"""
    line_pattern = re.compile(review.get("line", r".+"))
    covered = [re.compile(p, re.IGNORECASE) for p in review.get("covered", [])]
    lines = [line.strip() for line in raw.splitlines() if line_pattern.search(line)]
    return [line for line in lines if not any(p.search(line) for p in covered)][:MAX_LINES]


def ai_judge(skill_name: str, cmd: str, lines: list[str]) -> dict | None:
    """让模型判断规则没覆盖的记录。返回 {"finding", "summary"}；模型不可用时返回 None。"""
    if config.MOCK:
        return None
    records = "\n".join(lines)
    try:
        passages = retrieve(records, k=PASSAGES)
    except Exception:
        passages = []
    context = "\n\n".join(f"[{i}] （{_cite_label(p)}）\n{p['text']}" for i, p in enumerate(passages, 1))
    user = f"技能：{skill_name}\n命令：{cmd}\n\n未覆盖的记录：\n{records}\n\n手册片段：\n{context or '（无）'}"
    try:
        reply = json.loads(chat([{"role": "system", "content": PROMPT.format(n=len(passages) or 1)},
                                 {"role": "user", "content": user}], schema=SCHEMA))
    except (LLMError, ValueError):
        return None
    n = reply.get("source", 0)
    sources = []
    if isinstance(n, int) and 1 <= n <= len(passages):
        p = passages[n - 1]
        sources = [{"label": _cite_label(p), "file": p["file"], "page": p.get("page"), "section": p.get("section"),
                    "text": p["text"][:300], "via": "ai"}]
    finding = {
        "severity": reply["severity"],
        "title": reply["title"],
        "symptom": reply["symptom"],
        "root_cause": reply["root_cause"],
        "fix_commands": reply["fix_commands"][:6],
        "judged_by": "ai",
        "rule_path": ["规则树未覆盖", f"AI 推理：{cmd} 中 {len(lines)} 条记录"],
        "sources": sources,
        "ai_lines": lines,
    }
    return {"finding": finding, "summary": reply["summary"]}
