"""沉淀技能（FR-8）：把一次真实的排查结果保存成新的技能目录，下次可以直接执行。

| 文件 | 来源 |
|---|---|
| collect.yaml | 这次实际执行的命令（被拒绝、未执行的不收录） |
| rules.yaml   | 这次走过的规则（连同它们的结论）；AI 推理的结论转成一条规则，标注「待人工确认」 |
| refs.yaml    | 这些结论用到的手册章节号 |
| SKILL.md     | 名称、来源、采集命令、安全边界 |
| replay/      | 这次每条命令的输出，没有真实设备时回放 |
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import yaml

from . import executor
from .loader import SKILLS_DIR, load_skill


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or f"saved-skill-{int(time.time())}"


def _dump(data: dict) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)


def _ai_pattern(lines: list[str]) -> str:
    """从 AI 判断过的日志里取一个稳定的特征（日志标识，如 %%01MSTP/6/RECEIVE_MSTITC），用作规则。"""
    for line in lines:
        match = re.search(r"%%\d+[\w/]+", line)
        if match:
            return re.escape(match.group(0))
    return re.escape(lines[0][:40]) if lines else ".+"


def build(name: str, run: dict, skills_dir: Path | str | None = None, slug: str | None = None) -> dict:
    """根据一次执行结果（runner 的 done 数据）生成技能目录。返回 {"skill_id", "path", "errors"}。"""
    base = Path(skills_dir or SKILLS_DIR)
    source = load_skill(base / str(run.get("skill", "")))
    if not source["valid"]:
        raise ValueError(f"原技能 {run.get('skill')} 不可用，无法沉淀：" + "；".join(source["errors"]))
    title = name.strip() or "现场沉淀技能"
    saved_at = time.strftime("%Y-%m-%d %H:%M")

    # collect.yaml：这次实际执行了的命令，命令里的变量已经是这次的实际值
    commands, kept = [], set()
    for item in run.get("commands", []):
        if item.get("status") == "rejected" or item.get("mode") == "skipped":
            continue
        if not executor.check(item["cmd"], item.get("target", "local"))[0]:
            continue
        commands.append({"id": item["id"], "run": item["cmd"]} | ({"target": item["target"]} if item.get("target", "local") != "local" else {}))
        kept.add(item["id"])
    source_vars = (source["collect"].get("vars") or {}).keys()
    values = {k: str(v) for k, v in (run.get("vars") or {}).items() if k in source_vars}
    collect = {"platform": source["collect"].get("platform", "windows"),
               "timeout": source["collect"].get("timeout", executor.DEFAULT_TIMEOUT),
               "vars": values, "commands": commands}

    # rules.yaml：这次走过的规则，指向没走过的规则的分支改为结束
    tree = source["rules"]
    visited = [r["id"] for r in run.get("rules", []) if r.get("id")]
    by_id = {r["id"]: r for r in tree.get("rules", [])}
    rules = []
    for rule_id in visited:
        rule = by_id.get(rule_id)
        if not rule or rule["check"].get("cmd") not in kept:
            continue
        rule = yaml.safe_load(yaml.safe_dump(rule))  # 深拷贝
        for key in ("hit", "miss", "unknown"):
            if key in rule and rule[key].get("next", "end") not in visited:
                rule[key]["next"] = "end"
        rules.append(rule)
    rule_ids = {r["id"] for r in rules}
    for rule in rules:  # 指向被去掉的规则的分支也改为结束
        for key in ("hit", "miss", "unknown"):
            if key in rule and rule[key].get("next", "end") not in rule_ids:
                rule[key]["next"] = "end"
    findings = {}
    for rule in rules:
        for key in ("hit", "miss", "unknown"):
            fid = (rule.get(key) or {}).get("finding")
            if fid and fid in (tree.get("findings") or {}):
                findings[fid] = tree["findings"][fid]

    # AI 推理的结论：转成「日志里出现同样的记录 → 同样的结论」规则，标注待人工确认
    ai_rules, ai_refs = [], {}
    for n, finding in enumerate((f for f in run.get("findings", []) if f.get("judged_by") == "ai"), 1):
        lines = finding.get("ai_lines") or []
        review = next((r for r in tree.get("ai_review") or [] if r["cmd"] in kept), None)
        if not review or not lines:
            continue
        fid = f"ai-{n}"
        # AI 结论的出处：取所引手册片段的章节号（如 21.8.1.3），下次由 cite() 重新查
        numbers = [m.group(1) for src in finding.get("sources", [])
                   if (m := re.search(r"(?:^| > )(\d+(?:\.\d+)+) [^>]*$", src.get("section") or ""))]
        if numbers:
            ai_refs[fid] = {"sections": numbers}
        findings[fid] = {"severity": finding["severity"], "title": finding["title"], "symptom": finding["symptom"],
                         "root_cause": finding["root_cause"] + "（来自 AI 推理，待人工确认）",
                         "fix_commands": finding.get("fix_commands", []), "refs": [fid] if numbers else []}
        ai_rules.append({"id": fid, "label": f"AI 推理：{finding['title']}（待人工确认）",
                         "check": {"cmd": review["cmd"], "regex": _ai_pattern(lines)},
                         "hit": {"branch": "出现与上次相同的记录", "finding": fid, "next": "end"},
                         "miss": {"branch": "没有出现", "next": "end"}})
    if ai_rules:
        for rule, following in zip(ai_rules, ai_rules[1:]):
            rule["hit"]["next"] = rule["miss"]["next"] = following["id"]
        for rule in rules:  # 原来结束的分支，接到 AI 规则上
            for key in ("hit", "miss", "unknown"):
                if key in rule and rule[key].get("next") == "end":
                    rule[key]["next"] = ai_rules[0]["id"]
        rules += ai_rules
    if not rules:
        raise ValueError("这次执行没有可沉淀的规则")
    rules_doc = {"start": rules[0]["id"], "rules": rules, "findings": findings}
    reviews = [dict(r) for r in tree.get("ai_review") or [] if r["cmd"] in kept]
    for review in reviews:  # 已经转成规则的 AI 结论，不再重复交给 AI
        review["covered"] = list(review.get("covered", [])) + [r["check"]["regex"] for r in ai_rules]
    if reviews:
        rules_doc["ai_review"] = reviews

    # refs.yaml：这些结论用到的章节号
    source_refs = source["refs"].get("refs") or {}
    refs = {ref: source_refs[ref] for f in findings.values() for ref in f.get("refs", []) if ref in source_refs}
    refs.update(ai_refs)

    # SKILL.md
    skill_md = (
        f"# {title}\n\n"
        f"由「{source['name']}」在 {saved_at} 的一次排查沉淀，可以直接执行。\n\n"
        "## 采集命令\n\n" + "\n".join(f"- `{c['run']}`" + ("（交换机，回放）" if c.get("target") == "switch" else "")
                                     for c in commands)
        + "\n\n## 规则路径\n\n" + "\n".join(f"- {r['label']}" for r in rules)
        + "\n\n## 安全边界\n\n只执行白名单内的只读命令；报告中的修复命令只作为建议展示，不会自动执行。"
        + ("\nAI 推理得到的规则标注了「待人工确认」，确认前请勿直接采信。" if ai_rules else "") + "\n"
    )

    target = base / _slug(slug or name)
    if target.exists():
        target = base / f"{target.name}-{int(time.time())}"
    (target / "replay").mkdir(parents=True)
    (target / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (target / "collect.yaml").write_text(f"# 由「{source['name']}」{saved_at} 的排查结果生成\n" + _dump(collect), encoding="utf-8")
    (target / "rules.yaml").write_text(_dump(rules_doc), encoding="utf-8")
    (target / "refs.yaml").write_text(_dump({"refs": refs}), encoding="utf-8")
    for item in run.get("commands", []):
        if item["id"] not in kept:
            continue
        origin = item.get("replay_source") or ("本机真实执行" if item.get("mode") == "live" else "")
        header = f"# 来源：{saved_at} 排查时的输出" + (f"（{origin}）" if origin else "") + "\n"
        if item.get("status") != "success":
            header += f"# status: {item['status']}\n"
        (target / "replay" / f"{item['id']}.txt").write_text(header + (item.get("raw") or ""), encoding="utf-8")
    created = load_skill(target)
    return {"skill_id": target.name, "path": str(target), "errors": created["errors"]}
