"""Load and validate human-readable skill packages."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .executor import CommandRejected, validate_argv
from .rules import RuleError, evaluate


REQUIRED_FILES = ("SKILL.md", "collect.yaml", "rules.yaml", "refs.yaml")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class SkillValidationError(ValueError):
    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class SkillPackage:
    id: str
    path: Path
    name: str
    description: str
    collect: dict = field(default_factory=dict)
    rules: dict = field(default_factory=dict)
    refs: dict = field(default_factory=dict)
    valid: bool = True
    errors: list[str] = field(default_factory=list)

    def card(self):
        return {"id": self.id, "name": self.name, "description": self.description,
                "command_count": len(self.collect.get("commands", [])), "source": "skills/",
                "valid": self.valid, "errors": self.errors, "demo_ready": self.valid}


def _yaml(path: Path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SkillValidationError(f"{path.name} 无法解析：{exc}") from exc
    if not isinstance(data, dict):
        raise SkillValidationError(f"{path.name} 顶层必须是对象")
    return data


def _heading(path: Path, fallback: str) -> tuple[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    name = next((line.lstrip("#").strip() for line in lines if line.startswith("#")), fallback)
    description = next((line.strip() for line in lines if line.strip() and not line.startswith("#")), "本地只读排障技能")
    return name, description


class SkillLoader:
    def __init__(self, skills_root: Path | str, project_root: Path | str | None = None):
        self.skills_root = Path(skills_root)
        self.project_root = Path(project_root or self.skills_root.parent).resolve()

    def _static_reference(self, ref):
        source = ref.get("source")
        if not isinstance(source, dict):
            raise SkillValidationError(f"ref {ref.get('id')} 缺少 source")
        relative = source.get("path")
        text = source.get("text")
        if not isinstance(relative, str) or not isinstance(text, str) or not text.strip():
            raise SkillValidationError(f"ref {ref.get('id')} 的静态出处不完整")
        path = (self.project_root / relative).resolve()
        if not path.is_relative_to(self.project_root) or not path.is_file():
            raise SkillValidationError(f"ref {ref.get('id')} 的来源文件不存在或越界")
        if text not in path.read_text(encoding="utf-8"):
            raise SkillValidationError(f"ref {ref.get('id')} 的原文不在来源文件中")

    def load_dir(self, directory: Path | str) -> SkillPackage:
        directory = Path(directory)
        errors = []
        if not SAFE_ID.fullmatch(directory.name):
            errors.append("技能目录名必须是 2～64 位小写字母、数字、下划线或连字符")
        missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
        errors += [f"缺少 {name}" for name in missing]
        if errors:
            raise SkillValidationError("技能包结构无效", errors)
        name, description = _heading(directory / "SKILL.md", directory.name)
        collect, rules, refs = _yaml(directory / "collect.yaml"), _yaml(directory / "rules.yaml"), _yaml(directory / "refs.yaml")
        commands = collect.get("commands")
        if not isinstance(commands, list) or not commands:
            errors.append("collect.yaml commands 必须是非空列表")
            commands = []
        ids = set()
        for command in commands:
            if not isinstance(command, dict) or not SAFE_ID.fullmatch(str(command.get("id", ""))):
                errors.append("每条命令需要合法且稳定的 id")
                continue
            if command["id"] in ids:
                errors.append(f"重复 command id：{command['id']}")
            ids.add(command["id"])
            try:
                validate_argv(command.get("argv"))
            except CommandRejected as exc:
                errors.append(f"{command['id']}：{exc}")
            if not isinstance(command.get("required", True), bool):
                errors.append(f"{command['id']} required 必须是布尔值")
        ref_items = refs.get("refs")
        if not isinstance(ref_items, list) or not ref_items:
            errors.append("refs.yaml refs 必须是非空列表")
            ref_items = []
        ref_ids = set()
        for ref in ref_items:
            if not isinstance(ref, dict) or not SAFE_ID.fullmatch(str(ref.get("id", ""))):
                errors.append("每条出处需要合法 id")
                continue
            if ref["id"] in ref_ids:
                errors.append(f"重复 ref id：{ref['id']}")
            ref_ids.add(ref["id"])
            resolver = ref.get("resolver")
            try:
                if resolver == "static":
                    self._static_reference(ref)
                elif resolver == "rag":
                    if not isinstance(ref.get("query"), str) or not ref["query"].strip():
                        raise SkillValidationError(f"ref {ref['id']} 缺少 RAG query")
                else:
                    raise SkillValidationError(f"ref {ref['id']} resolver 只允许 static/rag")
            except SkillValidationError as exc:
                errors += exc.errors
        rule_items = rules.get("rules")
        if not isinstance(rule_items, list) or not rule_items:
            errors.append("rules.yaml rules 必须是非空列表")
            rule_items = []
        rule_ids = set()
        for rule in rule_items:
            if not isinstance(rule, dict) or not SAFE_ID.fullmatch(str(rule.get("id", ""))):
                errors.append("每条规则需要合法 id")
                continue
            if rule["id"] in rule_ids:
                errors.append(f"重复 rule id：{rule['id']}")
            rule_ids.add(rule["id"])
            try:
                evaluate(rule.get("when"), {})
            except RuleError as exc:
                # Missing facts can be evaluated safely; schema errors cannot.
                if "不可比较" not in str(exc):
                    errors.append(f"{rule['id']}：{exc}")
            for branch in ("on_match", "on_miss"):
                finding = (rule.get(branch) or {}).get("finding")
                if finding:
                    unknown = set(finding.get("ref_ids", [])) - ref_ids
                    if unknown:
                        errors.append(f"{rule['id']} 引用了不存在的 refs：{sorted(unknown)}")
        if errors:
            raise SkillValidationError(f"技能 {directory.name} 校验失败", errors)
        return SkillPackage(directory.name, directory, name, description, collect, rules, refs)

    def load(self, skill_id: str) -> SkillPackage:
        if not isinstance(skill_id, str) or not SAFE_ID.fullmatch(skill_id):
            raise SkillValidationError("技能 ID 非法")
        directory = (self.skills_root / skill_id).resolve()
        root = self.skills_root.resolve()
        if not directory.is_relative_to(root) or not directory.is_dir():
            raise SkillValidationError("技能不存在")
        return self.load_dir(directory)

    def scan(self) -> list[SkillPackage]:
        result = []
        if not self.skills_root.exists():
            return result
        for directory in sorted(path for path in self.skills_root.iterdir() if path.is_dir() and not path.name.startswith(".")):
            try:
                result.append(self.load_dir(directory))
            except SkillValidationError as exc:
                name, description = _heading(directory / "SKILL.md", directory.name) if (directory / "SKILL.md").is_file() else (directory.name, "无效技能包")
                result.append(SkillPackage(directory.name, directory, name, description, valid=False, errors=exc.errors))
        return result
