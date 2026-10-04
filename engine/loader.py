"""技能库（FR-2）：扫描 skills/ 下的技能目录，读取并校验 4 个文件。

    skills/<id>/
    ├─ SKILL.md       名称（第一个标题）、适用场景、安全边界
    ├─ collect.yaml   采集哪些命令
    ├─ rules.yaml     规则树
    ├─ refs.yaml      每条结论对应的手册章节号
    └─ replay/        （可选）交换机命令的回放输出：<命令 id>.txt

新增一个目录就会出现在列表里；格式不对的技能标出原因（errors），不影响其他技能。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .simulator import SimulatorError, validate_simulator_mapping

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
TARGETS = {"local", "local_mac", "switch", "simulator"}


def _read_yaml(path: Path, errors: list[str]) -> dict:
    if not path.exists():
        errors.append(f"缺少 {path.name}")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        errors.append(f"{path.name} 格式错误：{exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path.name} 应为键值结构")
        return {}
    return data


def _read_markdown(path: Path) -> tuple[str | None, str]:
    """返回 (第一个标题, 标题后的第一段文字)。"""
    if not path.exists():
        return None, ""
    title, paragraph = None, []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if title is None:
            if text.startswith("#"):
                title = text.lstrip("#").strip() or None
            continue
        if text.startswith("#"):
            if paragraph:
                break
            continue
        if not text:
            if paragraph:
                break
            continue
        paragraph.append(text)
    return title, "".join(paragraph)


def _validate(skill: dict) -> list[str]:
    errors: list[str] = []
    supported_targets = skill["collect"].get("targets", ["local"])
    if (not isinstance(supported_targets, list) or not supported_targets
            or not all(isinstance(target, str) and target in {"local", "simulator"}
                       for target in supported_targets)
            or len(supported_targets) != len(set(supported_targets))):
        errors.append("collect.yaml targets 只允许不重复的 local/simulator")
    commands = skill["collect"].get("commands")
    if not isinstance(commands, list) or not commands:
        return ["collect.yaml 里没有命令"]
    ids = set()
    for item in commands:
        if not isinstance(item, dict) or "id" not in item or "run" not in item:
            return ["collect.yaml 是旧格式：每条命令需要 id 和 run"]
        target = item.get("target", "local")
        if target not in TARGETS:
            errors.append(f"命令 {item['id']} 的 target 只能是 local、local_mac、switch 或 simulator")
        if isinstance(item["run"], dict) and not set(item["run"]) <= {"windows", "mac"}:
            errors.append(f"命令 {item['id']} 的 run 只能按 windows / mac 分别写")
        if target == "simulator":
            try:
                validate_simulator_mapping({"action": item.get("action", "command"),
                                            "device": item.get("device"), "command": item["run"]})
            except SimulatorError as exc:
                errors.append(f"命令 {item['id']}：{exc}")
        ids.add(item["id"])

    tree = skill["rules"]
    rules = tree.get("rules")
    if not isinstance(rules, list) or not rules or not all(isinstance(r, dict) and "id" in r for r in rules):
        return errors + ["rules.yaml 不是规则树格式（需要 start 和 rules）"]
    rule_ids = {r["id"] for r in rules}
    findings = tree.get("findings") or {}
    refs = skill["refs"].get("refs") or {}
    if tree.get("start") not in rule_ids:
        errors.append("rules.yaml 的 start 不存在")
    for rule in rules:
        check = rule.get("check") or {}
        if check.get("cmd") not in ids:
            errors.append(f"规则 {rule['id']} 引用了不存在的命令 {check.get('cmd')}")
        for key in ("hit", "miss", "unknown"):
            outcome = rule.get(key)
            if outcome is None:
                if key != "unknown":
                    errors.append(f"规则 {rule['id']} 缺少 {key} 分支")
                continue
            target = outcome.get("next", "end")
            if target != "end" and target not in rule_ids:
                errors.append(f"规则 {rule['id']} 的 {key} 指向不存在的规则 {target}")
            if outcome.get("finding") and outcome["finding"] not in findings:
                errors.append(f"规则 {rule['id']} 引用了不存在的结论 {outcome['finding']}")
    for finding_id, finding in findings.items():
        for ref in finding.get("refs", []):
            if ref not in refs:
                errors.append(f"结论 {finding_id} 引用了 refs.yaml 里没有的 {ref}")
    for review in tree.get("ai_review") or []:
        if review.get("cmd") not in ids:
            errors.append(f"ai_review 引用了不存在的命令 {review.get('cmd')}")
    return errors


def load_skill(skill_dir: Path | str) -> dict:
    """读取一个技能目录。返回 {id, dir, name, description, collect, rules, refs, errors, valid}。"""
    skill_dir = Path(skill_dir)
    errors: list[str] = []
    name, description = _read_markdown(skill_dir / "SKILL.md")
    skill = {
        "id": skill_dir.name,
        "dir": skill_dir,
        "name": name or skill_dir.name,
        "description": description,
        "collect": _read_yaml(skill_dir / "collect.yaml", errors),
        "rules": _read_yaml(skill_dir / "rules.yaml", errors),
        "refs": _read_yaml(skill_dir / "refs.yaml", errors),
    }
    if not errors:
        errors = _validate(skill)
    skill["errors"] = errors
    skill["valid"] = not errors
    return skill


def list_skills(skills_dir: Path | str | None = None) -> list[dict]:
    """列出所有包含 collect.yaml 的技能目录（含格式错误的，见 errors）。"""
    base = Path(skills_dir) if skills_dir else SKILLS_DIR
    if not base.exists():
        return []
    return [load_skill(p) for p in sorted(base.iterdir()) if p.is_dir() and (p / "collect.yaml").exists()]


def all_ref_sections(skill: dict) -> list[str]:
    return [str(s) for ref in (skill["refs"].get("refs") or {}).values() for s in ref.get("sections", [])]
