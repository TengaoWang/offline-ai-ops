"""对话里的「排查」动作：用户在 answer() 对话里描述现场故障时，执行技能并把报告作为回答。

    answer("MES 服务器连不上了，帮我查一下")
      → 调度器判断为 diagnose，选技能 net-unreachable，参数 target 从这句话或长期记忆里取
      → engine 执行技能（白名单命令 → 规则树 → 规则没覆盖的交给 AI → 手册出处）
      → 模型结合以前的排查记录写一段总结
      → 这次的排查写入长期记忆

技能、命令、判定都由 engine 完成，模型只负责选技能、取参数和最后的总结；出处由程序查手册，不由模型写。
"""

from __future__ import annotations

import re
import time

from . import memory
from .client import LLMError
from .client import chat as _chat

_VALUE = re.compile(r"^[A-Za-z0-9][\w.:/-]{0,63}$")  # 技能参数只接受 IP、端口名、数字这类值
_PORT_ALIASES = [(re.compile(r"^(?:XGE|XG)\s*(\d+/\d+/\d+)$", re.I), "XGigabitEthernet"),
                 (re.compile(r"^(?:GE|Gi|G)\s*(\d+/\d+/\d+)$", re.I), "GigabitEthernet"),
                 (re.compile(r"^(?:Eth|E)\s*(\d+/\d+/\d+)$", re.I), "Ethernet")]


def normalize_value(value: str) -> str:
    """把口语里的接口简写换成设备输出里的全称：GE0/0/8 → GigabitEthernet0/0/8。"""
    value = (value or "").strip()
    for pattern, full in _PORT_ALIASES:
        match = pattern.match(value)
        if match:
            return f"{full}{match.group(1)}"
    return value


DUPLICATE_SCORE = 0.9  # 和已有的现场信息相似度超过这个值，算同一条

SEVERITY_ICON = {"critical": "🔴 严重", "warning": "🟡 警告", "ok": "🟢 正常"}

SUMMARY_PROMPT = """你是离线交换机运维助手。下面是刚才在现场执行排查技能得到的诊断报告，以及以前的相关排查记录。
用中文给用户写一段简短的总结（不超过 120 字）：
- 先说最重要的结论，以及第一步该怎么处理
- 如果和以前某次排查是同一个问题，明确说「和 X月X日 那次一样」，并说上次的结论
- 只根据报告和记录说话，不要编造报告里没有的结论、命令或页码"""


def available_skills() -> list[dict]:
    """可执行的技能：[{id, name, description, vars: {变量名: 说明}}]。engine 不可用时返回 []。"""
    try:
        from engine.loader import list_skills
    except Exception:
        return []
    skills = []
    for skill in list_skills():
        if not skill["valid"]:
            continue
        text = (skill["dir"] / "collect.yaml").read_text(encoding="utf-8")
        notes = dict(re.findall(r"^  (\w+):.*?#\s*(.+)$", text, re.M))
        skills.append({"id": skill["id"], "name": skill["name"], "description": skill["description"],
                       "vars": {name: notes.get(name, "") for name in (skill["collect"].get("vars") or {})}})
    return skills


def skills_text(skills: list[dict]) -> str:
    return "\n".join(
        f"- {s['id']}（{s['name']}）：{s['description']}"
        + ("\n  参数：" + "；".join(f"{k}（{v or '无说明'}）" for k, v in s["vars"].items()) if s["vars"] else "")
        for s in skills)


def _when(timestamp: float) -> str:
    return time.strftime("%m月%d日 %H:%M", time.localtime(timestamp))


def recall(question: str) -> dict:
    """查长期记忆：全部现场信息 + 和这句话相关的排查记录。"""
    memory.sync_from_files()
    return {"facts": memory.list_memories("fact"), "episodes": memory.search(question, k=3, kind="episode")}


def recall_text(recalled: dict) -> str:
    facts = "\n".join(f"- {f['text']}" + (f"（技能 {f['skill']} 的参数 {f['data']['var']} = {f['data']['value']}）"
                                          if f["data"].get("var") else "") for f in recalled["facts"])
    episodes = "\n".join(f"- [{_when(e['created'])}] {e['text']}" for e in recalled["episodes"])
    return f"已记住的现场信息：\n{facts or '（无）'}\n\n相关的历史排查记录：\n{episodes or '（无）'}"


def remember(facts: list[dict], skill_ids: set[str]) -> list[dict]:
    """保存调度器从这句话里提取的现场信息。"""
    saved = []
    for fact in facts or []:
        text = (fact.get("text") or "").strip()
        if not text:
            continue
        known = memory.search(text, k=1, kind="fact")
        if known and (known[0]["text"] == text or known[0]["score"] >= DUPLICATE_SCORE):
            continue  # 已经记住过（调度器有时会把记忆里的信息再抄一遍），不重复保存
        skill = fact.get("skill") if fact.get("skill") in skill_ids else None
        data = {}
        value = normalize_value(fact.get("value") or "")
        if skill and fact.get("var") and _VALUE.match(value):
            data = {"var": fact["var"], "value": value}
        saved.append(memory.add("fact", text, data, skill))
    return saved


def run(skill_id: str, variables: list[dict] | None = None, execution_mode: str = "real"):
    """执行技能，逐个产出 engine 的事件 (事件名, 数据)。

    参数：先用长期记忆里记住的，再用调度器从这句话里取到的（这句话里说的优先）；只接受该技能定义过的变量，
    值只能是 IP、端口名这类字符，最终命令还要过白名单。"""
    from engine.runner import run_skill

    overrides = memory.facts_for(skill_id)
    for item in variables or []:
        value = normalize_value(item.get("value") or "")
        if _VALUE.match(value):
            overrides[item["name"]] = value
    if execution_mode not in {"real", "simulation"}:
        raise ValueError("execution_mode 只允许 real 或 simulation")
    yield from run_skill(skill_id, overrides=overrides, replay_only=execution_mode == "simulation")


def citations(run_result: dict) -> tuple[list[dict], dict]:
    """报告里所有出处去重编号，返回 (citations, {出处 label: 编号})，格式和 ask() 的 citations 一样。"""
    numbered, index = [], {}
    for finding in run_result["findings"]:
        for source in finding.get("sources") or []:
            if source["label"] not in index:
                index[source["label"]] = len(numbered) + 1
                numbered.append({"n": index[source["label"]], "file": source.get("file"), "page": source.get("page"),
                                 "section": source.get("section"), "label": source["label"],
                                 "text": source.get("text", "")})
    return numbered, index


def report_text(run_result: dict, index: dict) -> str:
    """把诊断报告写成文字：分级、现象、根因、修复命令（只建议）、出处编号。"""
    lines = []
    for f in run_result["findings"]:
        refs = "".join(f"[{index[s['label']]}]" for s in f.get("sources") or []) or "（手册中未找到依据）"
        source = "规则树" if f["judged_by"] == "rule" else "AI 推理"
        lines.append(f"{SEVERITY_ICON.get(f['severity'], f['severity'])}  {f['title']}（{source}）{refs}")
        lines.append(f"   现象：{f['symptom']}")
        lines.append(f"   根因：{f['root_cause']}")
        if f.get("fix_commands"):
            lines.append("   建议步骤（不会自动执行，操作前请备份配置）：" + " → ".join(f["fix_commands"]))
    for item in run_result.get("unresolved") or []:
        lines.append(f"仍需人工确认：{item}")
    return "\n".join(lines)


def summarize(question: str, run_result: dict, episodes: list[dict]) -> str:
    """模型结合这次的报告和以前的排查记录写总结；模型不可用时用报告第一条。"""
    _, index = citations(run_result)
    past = "\n".join(f"- [{_when(e['created'])}] {e['text']}" for e in episodes) or "（无）"
    try:
        return _chat([{"role": "system", "content": SUMMARY_PROMPT},
                      {"role": "user", "content": f"用户的问题：{question}\n\n诊断报告：\n{report_text(run_result, index)}"
                                                  f"\n\n以前的排查记录：\n{past}"}]).strip()
    except LLMError:
        problems = [f for f in run_result["findings"] if f["severity"] != "ok"]
        return f"排查完成：{problems[0]['title']}。" if problems else "排查完成，没有发现异常。"


def save_episode(question: str, skill_id: str, run_result: dict) -> dict:
    """把这次排查写入长期记忆。"""
    problems = [f for f in run_result["findings"] if f["severity"] in ("critical", "warning")]
    conclusion = "；".join(f["title"] for f in problems) or "未发现异常"
    fix = next((f["fix_commands"] for f in problems if f.get("fix_commands")), [])
    text = (f"问题：{question}。技能：{skill_id}。结论：{conclusion}。"
            + (f"建议处理：{' → '.join(fix[:5])}。" if fix else ""))
    data = {"vars": run_result.get("vars", {}), "elapsed": run_result.get("elapsed"),
            "findings": [{"severity": f["severity"], "title": f["title"]} for f in run_result["findings"]]}
    return memory.add("episode", text, data, skill_id)
