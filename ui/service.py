"""One process, one bounded operation. No queue, retry, or hidden demo fallback."""
from pathlib import Path
import threading
import time
import uuid

from llm import answer, health, route, config
from llm import kb
from llm import memory
from llm.client import LLMTimeout
from engine import EngineError, SkillEngine, SkillValidationError
from engine import executor
from engine.simulator import SimulatorError, normalize_simulator_target


ROOT = Path(__file__).resolve().parent.parent


class APIError(RuntimeError):
    def __init__(self, message, code="invalid_request", status=400):
        super().__init__(message)
        self.code, self.status = code, status


class Operations:
    def __init__(self):
        self.lock = threading.Lock()
        self.name = None
        self.recovering = False
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.runs = {}
        self.runs_lock = threading.Lock()
        self.engine = SkillEngine(ROOT / "skills", ROOT / "runtime", ROOT)

    def begin(self, name):
        if self.recovering:
            raise APIError("模型后台状态未知，请恢复 Ollama 后重启本服务", "recovering", 503)
        if not self.lock.acquire(blocking=False):
            raise APIError("正在问答或建库，请等待当前操作结束", "busy", 409)
        # A timeout can have set recovering while this thread was acquiring.
        if self.recovering:
            self.lock.release()
            raise APIError("模型后台状态未知，请恢复服务", "recovering", 503)
        self.name = name

    def end(self):
        self.name = None
        self.lock.release()

    def status(self):
        return {"busy": self.lock.locked(), "operation": self.name, "recovering": self.recovering}

    def run(self, name, function):
        self.begin(name)
        try:
            return function()
        except LLMTimeout:
            self.recovering = True
            raise
        finally:
            self.end()

    def ask(self, payload):
        question, history = validate_question(payload)
        locale = "en" if payload.get("locale") == "en" else "zh-CN"
        agent_mode = payload.get("agent_mode", False)
        execution_mode = payload.get("execution_mode", "real")
        if not isinstance(agent_mode, bool):
            raise APIError("agent_mode 必须是布尔值")
        if execution_mode not in {"real", "simulation"}:
            raise APIError("execution_mode 只允许 real 或 simulation")
        def work():
            status = health()
            if not config.MOCK and not status["rag_ready"]:
                raise APIError("问答未就绪：请检查 Ollama、问答模型和有效索引。" + "；".join(status["errors"]), "not_ready", 503)
            snapshot = kb.current()
            result = answer(question, history=conversation_turns(history), locale=locale,
                            diagnose=agent_mode, execution_mode=execution_mode)
            if result.get("run"):
                run_id = "run-" + uuid.uuid4().hex
                completed = result["run"] | {
                    "run_id": run_id,
                    "execution_mode": execution_mode,
                    "target": {"kind": "local", "display_name": "localhost"},
                    "issue": question,
                }
                with self.runs_lock:
                    self.runs[run_id] = {"run_id": run_id, "state": "succeeded", "events": [],
                                         "result": completed, "error": None,
                                         "condition": threading.Condition(self.runs_lock),
                                         "execution_mode": execution_mode, "created_at": time.time()}
                result["run"] = completed
            answer_type = result["answer_type"]
            found = answer_type in {"generated", "extracted"} and bool(result["citations"])
            warnings = []
            if answer_type == "extracted":
                warnings.append("The model summary did not pass verification. The original manual excerpt is shown; interpret it in context."
                                if locale == "en" else
                                "模型整理结果未通过核对，当前展示手册原文，请结合上下文判断。")
            refusal = {"clarify": "clarification_required", "out_of_scope": "out_of_scope",
                       "not_found": "no_evidence"}.get(answer_type)
            return result | {
                "found": found,
                "execution_mode": result.get("run", {}).get("execution_mode") if result.get("run") else
                                  ("mock" if config.MOCK else "real"),
                "verification_status": "citation_and_command_checked" if answer_type == "generated" else
                                       "source_extract" if answer_type == "extracted" else "not_run",
                "refusal_reason": refusal,
                "index_revision": snapshot["revision"] if snapshot else None,
                "retrieval_mode": status["retrieval_mode"] if result["action"] == "answer" else None,
                "warnings": warnings,
                "request_id": payload.get("request_id"),
                "conversation_id": payload.get("conversation_id"),
            }
        return self.run("问答处理中", work)

    def list_memories(self):
        memory.sync_from_files()
        items = memory.list_memories()
        return {"memories": items, "facts_count": sum(x["kind"] == "fact" for x in items),
                "episodes_count": sum(x["kind"] == "episode" for x in items)}

    def forget_memory(self, identifier):
        try:
            memory_id = int(identifier)
        except (TypeError, ValueError) as exc:
            raise APIError("无效的记忆 ID") from exc
        if memory_id < 1 or not memory.forget(memory_id):
            raise APIError("记忆不存在", "memory_unknown", 404)
        return {"ok": True, "memory_id": memory_id}

    def simulator_check(self, payload):
        command = payload.get("command")
        if not isinstance(command, str) or not 1 <= len(command.strip()) <= 500:
            raise APIError("命令应为 1～500 字符")
        command = " ".join(command.strip().split())
        first = command.split(" ", 1)[0].lower()
        # The simulator validates syntax only and never executes the command, so
        # use the Windows-style local table as a portable fallback on Linux.
        target = "switch" if first in {"display", "dir"} else (executor.local_target() or "local")
        allowed, reason = executor.check(command, target)
        samples = {
            "display version": "Huawei Versatile Routing Platform Software\nVRP (R) software, Version 5.170 (S5700 V200R019C10)",
            "display interface brief": "Interface                         PHY   Protocol  InUti OutUti\nGE0/0/8                           up    up        0.01% 0.02%\nGE0/0/9                           up    down      0.00% 0.00%",
            "display vlan 10": "VID  Type  Ports\n10   common GE0/0/8(U) GE0/0/10(U)",
            "ping 192.168.10.1": "PING 192.168.10.1\nReply from 192.168.10.1\nSuccess rate is 100 percent (1/1)",
            "ping 192.168.10.20": "PING 192.168.10.20\nRequest timeout.\nSuccess rate is 0 percent (0/1)",
        }
        return {"command": command, "allowed": allowed, "reason": reason, "target": target,
                "output": samples.get(command.lower()) if allowed else None,
                "simulated": True}

    def route(self, payload):
        text = payload.get("text")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise APIError("故障描述应为 1～4000 字符")
        return self.run("技能路由", lambda: route(text))

    def list_skills(self):
        return self.engine.list_skills()

    def _append_run_event(self, identifier, event, data):
        with self.runs_lock:
            record = self.runs[identifier]
            sequence = len(record["events"]) + 1
            record["events"].append({"sequence": sequence, "event": event, "data": data,
                                     "created_at": time.time()})
            record["condition"].notify_all()

    def start_diagnosis(self, payload):
        issue = payload.get("issue", "")
        skill_id = payload.get("skill_id")
        mode = payload.get("execution_mode", "real")
        if not isinstance(issue, str) or len(issue) > 4000:
            raise APIError("故障描述必须是不超过4000字符的文本")
        if skill_id is not None and not isinstance(skill_id, str):
            raise APIError("skill_id 必须是字符串")
        if not skill_id and not issue.strip():
            raise APIError("请选择技能或填写故障描述")
        if mode not in {"real", "simulation"}:
            raise APIError("execution_mode 只允许 real 或 simulation")
        target = payload.get("target") or {"kind": "local", "display_name": "localhost"}
        if not isinstance(target, dict) or target.get("kind") not in {"local", "simulator"}:
            raise APIError("目标类型只允许 local 或 simulator")
        if target["kind"] == "simulator":
            if mode != "simulation":
                raise APIError("交换机模拟器必须使用 simulation 执行模式")
            try:
                target = normalize_simulator_target(target)
            except SimulatorError as exc:
                raise APIError(str(exc), exc.code, exc.status) from exc
        if skill_id:
            try:
                self.engine.loader.load(skill_id)
            except SkillValidationError as exc:
                raise APIError("；".join(exc.errors), "invalid_skill", 400) from exc
        self.begin("真实诊断执行中")
        identifier = "run-" + uuid.uuid4().hex
        condition = threading.Condition(self.runs_lock)
        with self.runs_lock:
            self.runs[identifier] = {"run_id": identifier, "state": "running", "events": [],
                                     "result": None, "error": None, "condition": condition,
                                     "execution_mode": mode, "created_at": time.time()}

        def worker():
            try:
                selected = skill_id
                if not selected:
                    routed = route(issue.strip())
                    selected = routed.get("skill")
                    if not selected:
                        raise EngineError("当前描述未匹配到可执行技能，请手动选择技能", "no_skill", 422)
                    self.engine.loader.load(selected)
                result = self.engine.run(selected, target=target, mode=mode, issue=issue.strip(),
                                         run_id=identifier,
                                         emit=lambda event, data: self._append_run_event(identifier, event, data))
                with self.runs_lock:
                    record = self.runs[identifier]
                    record.update(state="succeeded", result=result)
                    record["condition"].notify_all()
            except Exception as exc:
                if isinstance(exc, LLMTimeout):
                    self.recovering = True
                error = {"message": str(exc), "code": getattr(exc, "code", "diagnosis_failed"),
                         "status": getattr(exc, "status", 500)}
                self._append_run_event(identifier, "error", error)
                with self.runs_lock:
                    record = self.runs[identifier]
                    record.update(state="failed", error=error)
                    record["condition"].notify_all()
            finally:
                self.end()

        threading.Thread(target=worker, daemon=True).start()
        return {"run_id": identifier, "state": "running", "execution_mode": mode}

    def diagnosis_run(self, identifier):
        if not isinstance(identifier, str) or not identifier.startswith("run-"):
            raise APIError("无效的运行 ID")
        with self.runs_lock:
            record = self.runs.get(identifier)
            if not record:
                raise APIError("运行不存在或服务已重启", "run_unknown", 404)
            return {key: value for key, value in record.items() if key not in {"condition", "events"}}

    def diagnosis_events(self, identifier, after=0):
        if not isinstance(identifier, str) or not identifier.startswith("run-"):
            raise APIError("无效的运行 ID")
        cursor = max(0, int(after))
        while True:
            with self.runs_lock:
                record = self.runs.get(identifier)
                if not record:
                    raise APIError("运行不存在或服务已重启", "run_unknown", 404)
                while len(record["events"]) <= cursor and record["state"] == "running":
                    record["condition"].wait(timeout=10)
                events = list(record["events"][cursor:])
                state = record["state"]
            for event in events:
                cursor = event["sequence"]
                yield event
            if state != "running" and not events:
                break
            if state != "running" and cursor >= len(record["events"]):
                break

    def save_skill(self, payload):
        identifier = payload.get("run_id")
        name = payload.get("name")
        if not isinstance(identifier, str) or not isinstance(name, str):
            raise APIError("run_id 和 name 必填")
        with self.runs_lock:
            record = self.runs.get(identifier)
            if not record or record["state"] != "succeeded" or not record["result"]:
                raise APIError("只能保存本服务内已完成的诊断运行", "invalid_run", 409)
            result = record["result"]
        try:
            return self.engine.save_skill(result, name, payload.get("slug"))
        except EngineError as exc:
            raise APIError(str(exc), exc.code, exc.status) from exc

    def start_build(self, payload):
        if "base_revision" not in payload:
            raise APIError("请先刷新当前知识库版本再提交")
        ids, replacements = payload.get("upload_ids", []), payload.get("replace_names", [])
        if not isinstance(ids, list) or len(ids) > 10 or len(set(str(x) for x in ids)) != len(ids):
            raise APIError("upload_ids 应为不重复的列表，最多10份")
        for identifier in ids:
            kb.object_dir(config.KB_ROOT, "staging", identifier)
        if not isinstance(replacements, list) or not all(isinstance(x, str) for x in replacements):
            raise APIError("replace_names 应为文件名列表")
        self.begin("知识库构建中，暂停问答")
        try:
            snapshot = kb.check_base(payload["base_revision"])
            # Reject unconfirmed replacements synchronously before admitting a job.
            import json
            existing = {x["name"] for x in snapshot["manifest"]["files"]} if snapshot else set()
            for identifier in ids:
                try:
                    meta = json.loads((kb.object_dir(config.KB_ROOT, "staging", identifier) / "upload.json").read_text())
                except (OSError, ValueError) as exc:
                    raise APIError("暂存文件不可用，请重新上传", "invalid_upload") from exc
                if meta["name"] in existing and meta["name"] not in replacements:
                    raise APIError("同名文件需要明确确认替换", "replacement_required", 409)
            identifier = "j-" + uuid.uuid4().hex
            with self.jobs_lock:
                self.jobs[identifier] = {"job_id": identifier, "state": "running", "phase": "准备手册快照"}
            def update(**values):
                with self.jobs_lock:
                    self.jobs[identifier].update(values)
            def worker():
                try:
                    result = kb.build(ids, payload["base_revision"], replacements, progress=lambda phase: update(phase=phase))
                    update(state="succeeded", result=result, phase="已发布")
                except Exception as exc:
                    if isinstance(exc, LLMTimeout):
                        self.recovering = True
                    update(state="failed", error=str(exc), code=getattr(exc, "code", "build_failed"))
                finally:
                    self.end()
            threading.Thread(target=worker, daemon=True).start()
            return {"job_id": identifier}
        except Exception:
            self.end()
            raise

    def job(self, identifier):
        with self.jobs_lock:
            if identifier not in self.jobs:
                raise APIError("任务不存在或服务已重启，无法恢复；请检查当前发布版本", "job_unknown", 404)
            return dict(self.jobs[identifier])


def validate_question(payload):
    question = payload.get("question")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
        raise APIError("问题应为 1～4000 字符")
    history = payload.get("history", [])
    if not isinstance(history, list) or len(history) > 20:
        raise APIError("history 必须为最多20条消息的列表")
    total = 0
    for message in history:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"} or not isinstance(message.get("content"), str):
            raise APIError("历史消息仅允许 user/assistant 文本")
        for optional in ("action", "query", "suggest_skill"):
            if message.get(optional) is not None and (not isinstance(message[optional], str) or len(message[optional]) > 4000):
                raise APIError("历史消息附加字段无效")
        total += len(message["content"])
    if total > 16000:
        raise APIError("历史消息超过16000字符")
    for name in ("request_id", "conversation_id"):
        if payload.get(name) is not None and (not isinstance(payload[name], str) or len(payload[name]) > 128):
            raise APIError("无效的会话或请求 ID")
    return question.strip(), history[-8:]


def conversation_turns(messages):
    """Convert UI role/content messages to the turn format required by llm.qa."""
    turns, pending = [], None
    for message in messages:
        if message["role"] == "user":
            pending = message["content"]
        elif pending is not None:
            turn = {"question": pending, "answer": message["content"],
                    "action": message.get("action", "answer")}
            if isinstance(message.get("query"), str):
                turn["query"] = message["query"][:4000]
            if message.get("suggest_skill") in {"net-unreachable", "disk-full", "service-down", "log-audit"}:
                turn["suggest_skill"] = message["suggest_skill"]
            turns.append(turn)
            pending = None
    return turns[-2:]


operations = Operations()
