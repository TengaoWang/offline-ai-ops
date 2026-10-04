"""串起整个诊断流程：采集（FR-3）→ 规则树（FR-4）→ AI 补充（FR-5）→ 报告（FR-6）→ 出处（FR-7）。

run_skill() 逐步产出 (事件名, 数据)，事件和字段与界面原来的演示数据（ui/server.py 的 DEMO_RUNS）一致：
    start → collect（每条命令一次）→ rules → ai（有 AI 补充时）→ report → done
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Iterator

from llm.cite import cite

from . import executor, judge, rules
from .loader import SKILLS_DIR, load_skill
from .simulator import SimulatorClient

COLLECT_BUDGET = 30  # 秒，FR-3：30 秒内完成全部采集
SEVERITY_ORDER = {"critical": 0, "warning": 1, "ok": 2}


def _resolve_vars(spec: dict, results: dict, overrides: dict | None = None) -> dict:
    """计算 collect.yaml 里的变量。优先级：调用时传入（overrides，例如 AI 从对话或记忆里取到的地址）
    > 环境变量 OPS_<名称> > 从命令输出提取（from）> 默认值。"""
    values = {}
    for name, value in (spec or {}).items():
        env = (overrides or {}).get(name) or os.environ.get(f"OPS_{name.upper()}")
        if env:
            values[name] = env
        elif isinstance(value, dict):
            found = None
            sources = value.get("from")
            for source in sources if isinstance(sources, list) else [sources]:  # 可以从多条命令里找
                result = results.get(source)
                match = re.search(value["regex"], result["raw"], re.IGNORECASE | re.MULTILINE) \
                    if result and result.get("raw") else None
                if match:  # 正则可以有多个分组（例如 Windows、macOS 两种格式），取第一个有值的
                    found = next((g for g in match.groups() if g), None)
                    break
            values[name] = found or value.get("default", "")
        else:
            values[name] = str(value)
    return values


def _pick_command(item: dict, replay_only: bool = False) -> tuple[str | None, str]:
    """选出这条命令在当前系统上的写法。返回 (命令, target)。

    run 可以是一条命令（target 默认 local，即 Windows 写法），也可以按系统分别写：
        run: {windows: ping -n 2 -w 1000 ${gateway}, mac: ping -c 2 -t 2 ${gateway}}
    macOS 上真实执行 mac 写法；Windows 上真实执行 windows 写法；其他情况读回放（显示 windows 写法）。"""
    run = item["run"]
    if not isinstance(run, dict):
        return run, item.get("target", "local")
    if not replay_only and executor.local_target() == "local_mac" and "mac" in run and executor.live_supported("local_mac"):
        return run["mac"], "local_mac"
    if "windows" in run:
        return run["windows"], "local"
    return None, "local"


def _collect(skill: dict, runner=None, overrides: dict | None = None, replay_only: bool = False,
             simulator_client: SimulatorClient | None = None) -> Iterator[dict]:
    """按顺序执行采集命令，每条执行完就产出结果。"""
    collect = skill["collect"]
    timeout = float(collect.get("timeout", executor.DEFAULT_TIMEOUT))
    results: dict[str, dict] = {}
    started = time.monotonic()
    for item in collect["commands"]:
        command, target = _pick_command(item, replay_only)
        if command is None:  # 这条命令没有当前系统的写法（例如只在 macOS 上用的 netstat -rn），跳过
            continue
        values = _resolve_vars(collect.get("vars"), results, overrides)
        command = rules.fill(command, values)
        if time.monotonic() - started > COLLECT_BUDGET:
            result = {"cmd": command, "status": "timeout", "duration": 0.0, "raw": "", "mode": "skipped",
                      "output": f"超出 {COLLECT_BUDGET} 秒采集时限，未执行", "replay_source": None}
        elif target == "simulator":
            if simulator_client is None:
                raise ValueError("模拟器命令缺少已连接的模拟器目标")
            result = executor.execute_simulator(command, item.get("device"), simulator_client,
                                                action=item.get("action", "command"))
        else:
            remaining = max(1.0, COLLECT_BUDGET - (time.monotonic() - started))
            result = executor.execute(command, target=target, timeout=min(timeout, remaining),
                                      replay=skill["dir"] / "replay" / f"{item['id']}.txt", runner=runner,
                                      force_replay=replay_only)
        result.update({"id": item["id"], "target": target})
        results[item["id"]] = result
        yield result


def _finding(skill: dict, finding_id: str, rule_path: list[str], values: dict) -> dict:
    spec = skill["rules"]["findings"][finding_id]
    refs = skill["refs"].get("refs") or {}
    sections, queries = [], []
    for ref_id in spec.get("refs", []):
        sections += [str(s) for s in refs[ref_id].get("sections", [])]
        if refs[ref_id].get("query"):
            queries.append(refs[ref_id]["query"])
    sources = cite(sections, query=queries[0] if queries else None) if sections or queries else []
    return {
        "severity": spec["severity"],
        "title": rules.fill(spec["title"], values),
        "symptom": rules.fill(spec.get("symptom", ""), values),
        "root_cause": rules.fill(spec.get("root_cause", ""), values),
        "fix_commands": [rules.fill(c, values) for c in spec.get("fix_commands", [])],
        "judged_by": "rule",
        "rule_path": rule_path,
        "sources": sources,
        "finding_id": finding_id,
        "refs": spec.get("refs", []),
    }


def run_skill(skill_id: str, skills_dir: Path | str | None = None, runner=None, use_ai: bool = True,
              overrides: dict | None = None, replay_only: bool = False,
              simulator_client: SimulatorClient | None = None) -> Iterator[tuple[str, dict]]:
    """执行一个技能，逐步产出 (事件名, 数据)。技能不存在或格式错误时抛出 ValueError。

    overrides：覆盖 collect.yaml 里的变量，例如 {"target": "192.168.10.20"}；只接受该技能定义过的变量。
    replay_only：全部命令读回放（界面的「模拟」模式）。"""
    started = time.monotonic()
    skill = load_skill(Path(skills_dir or SKILLS_DIR) / skill_id)
    if not skill["valid"]:
        raise ValueError(f"技能 {skill_id} 不可执行：" + "；".join(skill["errors"]))
    live = executor.live_supported() and not replay_only
    yield "start", {"skill": skill_id, "demo": False, "engine": True, "name": skill["name"], "live": live}

    commands, results = [], {}
    allowed = (skill["collect"].get("vars") or {}).keys()
    overrides = {k: str(v) for k, v in (overrides or {}).items() if k in allowed and v not in (None, "")}
    for index, result in enumerate(_collect(skill, runner, overrides, replay_only, simulator_client), 1):
        commands.append(result)
        results[result["id"]] = result
        yield "collect", {"index": index, **result}

    values = _resolve_vars(skill["collect"].get("vars"), results, overrides)
    outcome = rules.walk(skill["rules"], results, values)
    yield "rules", {"rules": outcome["path"]}

    findings = [_finding(skill, fid, path, vals) for fid, path, vals in outcome["findings"]]
    unresolved = list(outcome["unresolved"])
    unresolved += [f"命令 {c['cmd']} 超时，未采集到结果" for c in commands if c["status"] == "timeout"]

    ai_reasoning = ""
    for review in skill["rules"].get("ai_review") or []:
        result = results.get(review["cmd"])
        lines = judge.uncovered_lines(review, result.get("raw") or "") if result else []
        if not lines:
            continue
        judged = judge.ai_judge(skill["name"], result["cmd"], lines) if use_ai else None
        if judged:
            findings.append(judged["finding"])
            ai_reasoning = judged["summary"]
        else:
            unresolved.append(f"{result['cmd']} 中有 {len(lines)} 条记录规则未覆盖，AI 推理不可用，需人工查看")
    if ai_reasoning:
        yield "ai", {"text": ai_reasoning, "source": "AI 补充推理"}

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 3))
    elapsed = round(time.monotonic() - started, 1)
    yield "report", {"findings": findings, "unresolved": unresolved, "elapsed": elapsed}
    yield "done", {"skill": skill_id, "engine": True, "commands": commands, "rules": outcome["path"],
                   "ai_reasoning": ai_reasoning, "findings": findings, "unresolved": unresolved,
                   "elapsed": elapsed, "vars": outcome["values"]}


def run_skill_sync(skill_id: str, **kwargs) -> dict:
    """执行技能，只返回最终结果（done 事件的数据）。"""
    run = {}
    for event, data in run_skill(skill_id, **kwargs):
        if event == "done":
            run = data
    return run
