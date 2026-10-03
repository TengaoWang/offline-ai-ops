"""Skill orchestration: collect -> rules -> optional local AI -> sourced report."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable

import yaml

from llm import chat as default_chat
from llm import retrieve as default_retrieve
from llm.client import LLMProtocolError
from llm.rag import _unsupported_commands

from .executor import Executor
from .rules import evaluate_rules
from .skill_loader import SAFE_ID, SkillLoader, SkillValidationError


class EngineError(RuntimeError):
    def __init__(self, message, code="engine_error", status=400):
        super().__init__(message)
        self.code, self.status = code, status


AI_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "maxItems": 1, "items": {"type": "object", "properties": {
            "severity": {"enum": ["critical", "warning", "ok"]},
            "evidence_quote": {"type": "string"},
            "fix_commands": {"type": "array", "items": {"type": "string"}},
            "citations": {"type": "array", "items": {"type": "integer"}},
        }, "required": ["severity", "evidence_quote", "fix_commands", "citations"]}},
        "unresolved": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["findings", "unresolved"],
}

AI_PROMPT = """你是离线运维诊断证据选择器。只能根据“采集结果”从带编号的“手册片段”选择最多一条相关排查依据。
evidence_quote 必须逐字复制一条完整的中文说明句，不能选择设备日志、命令输出或只有英文状态的一行，也不能改写、概括或添加结论。不得生成采集命令，不得声称执行过任何修复。
fix_commands 必须在所引用原文中逐字出现；没有明确命令就返回空列表。证据不足的内容写入 unresolved，不要猜测。
输出严格符合 JSON Schema。"""


def _label(source: dict) -> str:
    base = f"《{Path(source['file']).stem}》"
    if source.get("section"):
        base += f" {source['section']}"
    if source.get("page") is not None:
        base += f" P{source['page']}"
    return base


class SkillEngine:
    def __init__(self, skills_root: Path | str, runtime_root: Path | str,
                 project_root: Path | str | None = None, retriever=None, chat_fn=None):
        self.skills_root = Path(skills_root)
        self.project_root = Path(project_root or self.skills_root.parent).resolve()
        self.loader = SkillLoader(self.skills_root, self.project_root)
        self.executor = Executor(Path(runtime_root) / "exec")
        self.retriever = retriever or default_retrieve
        self.chat_fn = chat_fn or default_chat

    def list_skills(self) -> list[dict]:
        return [package.card() for package in self.loader.scan()]

    def _resolve_ref(self, package, ref_id: str, cache: dict) -> dict | None:
        if ref_id in cache:
            return cache[ref_id]
        ref = next((item for item in package.refs["refs"] if item["id"] == ref_id), None)
        if not ref:
            return None
        if ref["resolver"] == "rag":
            hits = self.retriever(ref["query"], k=3)
            if not hits:
                return None
            hit = hits[0]
            source = {"file": hit["file"], "section": hit.get("section"), "page": hit.get("page"),
                      "text": hit["text"], "label": hit.get("label")}
        else:
            raw = ref["source"]
            source = {"file": raw["file"], "section": raw.get("section"), "page": raw.get("page"),
                      "text": raw["text"]}
        source["label"] = source.get("label") or _label(source)
        cache[ref_id] = source
        return source

    def _publish_rule_findings(self, package, candidates, unresolved, cache):
        published = []
        for candidate in candidates:
            sources = [self._resolve_ref(package, ref_id, cache) for ref_id in candidate.pop("ref_ids", [])]
            sources = [source for source in sources if source]
            if not sources:
                unresolved.append(f"{candidate.get('title', '规则结论')}：没有可解析出处，未发布")
                continue
            candidate["sources"] = sources
            published.append(candidate)
        return published

    def _ai_findings(self, package, issue, collected, unresolved):
        settings = package.rules.get("ai") or {}
        if not settings.get("enabled"):
            return []
        query = str(settings.get("query") or issue or package.name).strip()
        hits = self.retriever(query, k=5)
        if not hits:
            unresolved.append("AI 补充判定：本轮没有检索到可用手册依据")
            return []
        passages = hits[:3]
        evidence = "\n\n".join(f"[{index}] {_label(hit)}\n{hit['text']}" for index, hit in enumerate(passages, 1))
        summary = [{"command_id": item["command_id"], "status": item["status"],
                    "output": item["output"][:2000], "parsed": item["parsed"]} for item in collected]
        raw = self.chat_fn(
            [{"role": "system", "content": AI_PROMPT},
             {"role": "user", "content": f"故障描述：{issue or package.name}\n采集结果：{json.dumps(summary, ensure_ascii=False)}\n手册片段：\n{evidence}"}],
            schema=AI_SCHEMA, num_predict=256,
        )
        try:
            reply = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMProtocolError("AI 诊断返回了无效 JSON") from exc
        if not isinstance(reply, dict) or not isinstance(reply.get("findings"), list):
            raise LLMProtocolError("AI 诊断返回结构不符合契约")
        unresolved.extend(str(item) for item in reply.get("unresolved", []) if str(item).strip())
        result = []
        for finding in reply["findings"]:
            numbers = [n for n in dict.fromkeys(finding.get("citations", []))
                       if isinstance(n, int) and 1 <= n <= len(passages)]
            if not numbers:
                unresolved.append("AI 补充结论：没有合法出处编号，未发布")
                continue
            sources = [passages[n - 1]["text"] for n in numbers]
            quote = str(finding.get("evidence_quote", "")).strip()
            compact_quote = re.sub(r"\s+", "", quote)
            if not quote or not any(compact_quote in re.sub(r"\s+", "", source) for source in sources):
                unresolved.append("AI 补充结论：证据引文不是本轮出处原文，未发布")
                continue
            if not re.search(r"[\u4e00-\u9fff]", quote) or re.search(r"has turned into|%%\d|Interface\s+Gigabit", quote, re.I):
                unresolved.append("AI 补充结论：证据引文是日志/输出而非手册说明，未发布")
                continue
            unsupported = _unsupported_commands("\n".join(finding.get("fix_commands", [])), sources)
            if unsupported:
                unresolved.append(f"AI 补充结论：建议命令无原文支持 {unsupported}，未发布")
                continue
            citations = []
            for n in numbers:
                hit = passages[n - 1]
                citations.append({"file": hit["file"], "section": hit.get("section"), "page": hit.get("page"),
                                  "text": hit["text"], "label": hit.get("label") or _label(hit)})
            result.append({"severity": finding["severity"], "title": "AI 补充：手册相关排查依据",
                           "symptom": issue or "规则树缺少设备侧实时状态",
                           "root_cause": quote,
                           "fix_commands": list(finding.get("fix_commands", [])), "judged_by": "ai",
                           "rule_path": [], "sources": citations})
        return result

    def run(self, skill_id: str, target: dict | None = None, mode: str = "real", issue: str = "",
            emit: Callable[[str, dict], None] | None = None, enable_ai: bool = True,
            run_id: str | None = None) -> dict:
        if mode not in {"real", "simulation"}:
            raise EngineError("执行模式只允许 real 或 simulation", "invalid_mode")
        try:
            package = self.loader.load(skill_id)
        except SkillValidationError as exc:
            raise EngineError("；".join(exc.errors), "invalid_skill") from exc
        target = target or {"kind": "local", "display_name": "localhost"}
        if target.get("kind") != "local":
            raise EngineError("P0 只允许受控本机目标", "invalid_target")
        run_id = run_id or ("run-" + uuid.uuid4().hex)
        started = time.perf_counter()
        if emit:
            emit("start", {"run_id": run_id, "skill": skill_id, "execution_mode": mode,
                           "target": target, "simulation": mode == "simulation"})
        collect_started = time.perf_counter()
        collected = self.executor.execute(package.collect["commands"], mode, emit)
        collect_s = time.perf_counter() - collect_started
        facts = {"commands": {item["command_id"]: item for item in collected}}
        rule_path, candidates = evaluate_rules(package.rules["rules"], facts)
        if emit:
            emit("rules", {"rule_path": rule_path, "rules": rule_path})
        unresolved = [f"{item['command_id']} 未能获取：{item['status']} - {item['output'][:200]}"
                      for item in collected if item["status"] != "success"]
        cache = {}
        findings = self._publish_rule_findings(package, candidates, unresolved, cache)
        analysis_started = time.perf_counter()
        ai_settings = package.rules.get("ai") or {}
        needs_ai = ai_settings.get("trigger", "on_unmatched") == "always" or any(not item["matched"] for item in rule_path) or bool(unresolved)
        if enable_ai and ai_settings.get("enabled") and needs_ai:
            ai_findings = self._ai_findings(package, issue, collected, unresolved)
            findings.extend(ai_findings)
            if emit:
                emit("ai", {"findings": ai_findings, "text": "AI 补充判定已完成",
                            "source": "AI 补充推理", "judged_by": "ai"})
        analysis_s = time.perf_counter() - analysis_started
        total_s = time.perf_counter() - started
        timing = {"collect_s": round(collect_s, 3), "analysis_s": round(analysis_s, 3),
                  "total_s": round(total_s, 3)}
        result = {"run_id": run_id, "skill": skill_id, "execution_mode": mode, "target": target,
                  "collected": collected, "commands": collected, "rule_path": rule_path, "rules": rule_path,
                  "findings": findings, "unresolved": unresolved, "timing": timing, "elapsed": timing["total_s"]}
        if emit:
            emit("report", {"findings": findings, "unresolved": unresolved, "timing": timing,
                            "elapsed": timing["total_s"], "execution_mode": mode})
            emit("done", result)
        return result

    def save_skill(self, run: dict, name: str, slug: str | None = None) -> dict:
        if not isinstance(run, dict) or not run.get("run_id") or not run.get("skill") or not run.get("collected"):
            raise EngineError("只能从已完成的真实运行保存技能", "invalid_run")
        title = str(name or "").strip()
        if not 1 <= len(title) <= 80 or any(ch in title for ch in "\r\n\x00"):
            raise EngineError("技能名称必须为 1～80 个可显示字符", "invalid_name")
        candidate = (slug or re.sub(r"[^a-z0-9_-]+", "-", title.lower())).strip("-")
        if not SAFE_ID.fullmatch(candidate):
            candidate = "saved-" + uuid.uuid4().hex[:12]
        target = self.skills_root / candidate
        if target.exists():
            raise EngineError("同名技能已存在，未覆盖", "skill_exists", 409)
        source = self.loader.load(run["skill"])
        temporary = self.skills_root.parent / ("pending-" + uuid.uuid4().hex)
        temporary.mkdir(parents=True)
        try:
            for filename in ("collect.yaml", "rules.yaml", "refs.yaml"):
                shutil.copyfile(source.path / filename, temporary / filename)
            commands = "\n".join(f"- `{item['display']}`" for item in run["collected"])
            (temporary / "SKILL.md").write_text(
                f"# {title}\n\n由运行 `{run['run_id']}` 从 `{run['skill']}` 的已验证流程沉淀。\n\n"
                f"## 已执行的只读采集\n\n{commands}\n\n## 安全边界\n\n"
                "只执行 collect.yaml 中通过全局白名单的只读命令；修复建议永不自动执行。\n",
                encoding="utf-8")
            self.loader.load_dir(temporary)
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        package = self.loader.load(candidate)
        return {"skill_id": candidate, "path": str(target), "skill": package.card()}
