"""界面使用的 SkillEngine 接口（ui/service.py、eval/eval_p0_diagnostics.py 调用）。

接口和需求文档 §6.1 的契约一致：list_skills() / run(skill_id, target, mode, ...) / save_skill(run, name)。
内部用本目录的引擎执行：loader.py（技能库）→ runner.py（白名单执行、规则树、AI 补充、手册出处）→ skillgen.py（存为技能）。

和 runner.run_skill() 的区别只是字段名：这里额外给出界面要的 run_id、execution_mode、collected、
rule_path、timing、display、duration_s 等字段，原有字段保留。
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Callable

from . import skillgen
from .loader import list_skills as _list_skills
from .loader import load_skill
from .runner import run_skill

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class EngineError(RuntimeError):
    def __init__(self, message, code="engine_error", status=400):
        super().__init__(message)
        self.code, self.status = code, status


class SkillValidationError(ValueError):
    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = list(errors or [message])


class SkillLoader:
    """按 ID 读取并校验技能；不存在或格式错误时抛出 SkillValidationError。"""

    def __init__(self, skills_root: Path | str, project_root: Path | str | None = None):
        self.skills_root = Path(skills_root)

    def load(self, skill_id: str) -> dict:
        if not isinstance(skill_id, str) or not SAFE_ID.fullmatch(skill_id):
            raise SkillValidationError("技能 ID 非法")
        directory = (self.skills_root / skill_id).resolve()
        if not directory.is_relative_to(self.skills_root.resolve()) or not (directory / "collect.yaml").is_file():
            raise SkillValidationError("技能不存在")
        skill = load_skill(directory)
        if not skill["valid"]:
            raise SkillValidationError(f"技能 {skill_id} 校验失败", skill["errors"])
        return skill

    def scan(self) -> list[dict]:
        return _list_skills(self.skills_root)


def _card(skill: dict) -> dict:
    commands = skill["collect"].get("commands") or [] if skill["valid"] else []
    return {"id": skill["id"], "name": skill["name"], "description": skill["description"] or "本地只读排障技能",
            "command_count": len(commands), "source": "skills/", "valid": skill["valid"],
            "errors": skill["errors"], "demo_ready": skill["valid"]}


def _command(item: dict) -> dict:
    return item | {"command_id": item["id"], "display": item["cmd"], "duration_s": item["duration"],
                   "required": False, "returncode": None, "truncated": False, "parsed": {}}


def _rules(rules: list[dict]) -> list[dict]:
    return [rule | {"rule_id": rule["id"], "matched": rule["state"] == "hit"} for rule in rules]


class SkillEngine:
    def __init__(self, skills_root: Path | str, runtime_root: Path | str | None = None,
                 project_root: Path | str | None = None, retriever=None, chat_fn=None):
        self.skills_root = Path(skills_root)
        self.loader = SkillLoader(self.skills_root, project_root)

    def list_skills(self) -> list[dict]:
        return [_card(skill) for skill in self.loader.scan()]

    def run(self, skill_id: str, target: dict | None = None, mode: str = "real", issue: str = "",
            emit: Callable[[str, dict], None] | None = None, enable_ai: bool = True,
            run_id: str | None = None, overrides: dict | None = None) -> dict:
        """执行技能。mode：real（本机命令真实执行，交换机命令读手册示例回放）/ simulation（全部读回放）。"""
        if mode not in {"real", "simulation"}:
            raise EngineError("执行模式只允许 real 或 simulation", "invalid_mode")
        target = target or {"kind": "local", "display_name": "localhost"}
        if target.get("kind") != "local":
            raise EngineError("只允许受控本机目标", "invalid_target")
        try:
            self.loader.load(skill_id)
        except SkillValidationError as exc:
            raise EngineError("；".join(exc.errors), "invalid_skill") from exc
        run_id = run_id or ("run-" + uuid.uuid4().hex)
        send = emit or (lambda *_: None)
        started = time.perf_counter()
        collected_at = analysed_at = None
        result: dict = {}
        for event, data in run_skill(skill_id, skills_dir=self.skills_root, use_ai=enable_ai,
                                     overrides=overrides, replay_only=mode == "simulation"):
            if event == "start":
                send("start", data | {"run_id": run_id, "skill": skill_id, "execution_mode": mode,
                                      "target": target, "simulation": mode == "simulation"})
            elif event == "collect":
                send("collect", _command(data))
            elif event == "rules":
                collected_at = time.perf_counter()
                path = _rules(data["rules"])
                send("rules", {"rule_path": path, "rules": path})
            elif event == "ai":
                send("ai", data | {"judged_by": "ai"})
            elif event == "report":
                analysed_at = time.perf_counter()
                timing = {"collect_s": round((collected_at or analysed_at) - started, 3),
                          "analysis_s": round(analysed_at - (collected_at or analysed_at), 3),
                          "total_s": round(analysed_at - started, 3)}
                send("report", data | {"timing": timing, "execution_mode": mode})
            elif event == "done":
                commands = [_command(item) for item in data["commands"]]
                path = _rules(data["rules"])
                result = data | {"run_id": run_id, "execution_mode": mode, "target": target,
                                 "commands": commands, "collected": commands, "rules": path, "rule_path": path,
                                 "timing": timing, "issue": issue}
                send("done", result)
        return result

    def save_skill(self, run: dict, name: str, slug: str | None = None) -> dict:
        """把一次已完成的执行结果存成新技能目录（SKILL.md + collect.yaml + rules.yaml + refs.yaml + replay/）。"""
        if not isinstance(run, dict) or not run.get("skill") or not run.get("commands"):
            raise EngineError("只能从已完成的运行保存技能", "invalid_run")
        title = str(name or "").strip()
        if not 1 <= len(title) <= 80 or any(ch in title for ch in "\r\n\x00"):
            raise EngineError("技能名称必须为 1～80 个可显示字符", "invalid_name")
        candidate = (slug or re.sub(r"[^a-z0-9_-]+", "-", title.lower())).strip("-")
        if not SAFE_ID.fullmatch(candidate):
            candidate = "saved-" + uuid.uuid4().hex[:12]
        if (self.skills_root / candidate).exists():
            raise EngineError("同名技能已存在，未覆盖", "skill_exists", 409)
        try:
            created = skillgen.build(title, run, self.skills_root, slug=candidate)
        except ValueError as exc:
            raise EngineError(str(exc), "invalid_run") from exc
        if created["errors"]:
            raise EngineError("生成的技能未通过校验：" + "；".join(created["errors"]), "invalid_skill")
        return {"skill_id": created["skill_id"], "path": created["path"],
                "skill": _card(load_skill(Path(created["path"])))}
