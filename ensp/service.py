"""Independent eNSP diagnostics; neither imports nor waits for the RAG/UI packages."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from .models import CommandResult, EnspError, LabConfig
from .transport import ConsoleSession
from .vrp import MANUAL_REFERENCE, commands, is_vrp, parse_interface, parse_ping, require_allowed


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class EnspService:
    """One operation owns the consoles at a time. Events are plain JSON dictionaries."""

    def __init__(self, config: LabConfig, *, session_factory=ConsoleSession, mode: str = "live"):
        if mode not in ("live", "fixture"):
            raise ValueError("mode must be live or fixture")
        self.config, self.session_factory, self.mode = config, session_factory, mode
        self._lock = threading.Lock()
        self._history: OrderedDict[str, dict] = OrderedDict()

    def _collect(self, run_id: str, emit, health_only: bool = False) -> list[dict]:
        records: list[dict] = []
        for endpoint in (self.config.switch, self.config.probe):
            planned = commands(self.config)[endpoint.name]
            if health_only:
                planned = planned[:1]
            session, unavailable = None, None
            try:
                for command in planned:
                    require_allowed(self.config, endpoint.name, command)
                    started, tick = now(), time.monotonic()
                    emit("command_started", {"device": endpoint.name, "command": command})
                    output, error, status = "", unavailable, "skipped" if unavailable else "ok"
                    if not unavailable:
                        try:
                            if session is None:
                                session = self.session_factory(endpoint, self.config.timeout, self.config.encoding)
                                session.__enter__()
                            output = session.execute(command, lambda chunk: emit("command_output", {
                                "device": endpoint.name, "command": command, "chunk": chunk,
                            }))
                            if command == "display version" and not is_vrp(output):
                                raise EnspError("unexpected_device", "控制台响应未确认是华为 VRP，已停止对该端口的采集。")
                        except EnspError as exc:
                            error = {"code": exc.code, "message": str(exc)}
                            output = output or (session.last_output if session else "")
                            status = "timeout" if exc.code == "timeout" else "error"
                            # A command syntax error leaves a usable prompt; transport errors do not.
                            if exc.code != "command_failed" or command == "display version":
                                unavailable = error
                    result = CommandResult(endpoint.name, command, status, output, started,
                                           round((time.monotonic() - tick) * 1000), error).to_dict()
                    records.append(result)
                    emit("command_finished", {"result": result})
            finally:
                if session:
                    session.close()
        return records

    def health(self) -> dict:
        if not self._lock.acquire(blocking=False):
            raise EnspError("busy", "已有采集任务占用控制台，请稍后重试。")
        try:
            results = self._collect(str(uuid.uuid4()), lambda *_: None, health_only=True)
            return {"schema_version": "1.0", "mode": self.mode, "checked_at": now(),
                    "ready": all(r["status"] == "ok" for r in results), "devices": results,
                    "config": self.config.to_dict()}
        finally:
            self._lock.release()

    def diagnose(self, on_event=None, *, before_run_id: str | None = None, before: dict | None = None) -> dict:
        if not self._lock.acquire(blocking=False):
            raise EnspError("busy", "已有采集任务占用控制台，请稍后重试。")
        try:
            if before_run_id is not None:
                if not isinstance(before_run_id, str) or not before_run_id.strip():
                    raise EnspError("invalid_baseline", "复检需要先前诊断的有效 run_id。")
                before = self._history.get(before_run_id)
                if before is None:
                    raise EnspError("baseline_not_found", "找不到这次诊断的基线；服务重启后需重新采集。")
            if before is not None:
                self._validate_baseline(before)
            run_id, started = str(uuid.uuid4()), now()
            sequence = 0

            def emit(kind: str, data: dict):
                nonlocal sequence
                sequence += 1
                if on_event:
                    on_event({"event": kind, "run_id": run_id, "sequence": sequence,
                              "mode": self.mode, "timestamp": now(), **data})

            emit("run_started", {"operation": "verify" if before is not None else "diagnose"})
            collected = self._collect(run_id, emit)
            report = self._report(run_id, started, collected)
            if before is not None:
                old_passed = before["verification"]["passed"]
                new_passed = report["verification"]["passed"]
                if new_passed is True and old_passed is False:
                    recovery = "recovered"
                elif new_passed is True:
                    recovery = "healthy_without_failed_baseline"
                elif new_passed is False:
                    recovery = "not_recovered"
                else:
                    recovery = "unknown"
                report["recovery"] = {"status": recovery, "before_run_id": before["run_id"]}
            self._history[run_id] = copy.deepcopy(report)
            while len(self._history) > 20:
                self._history.popitem(last=False)
            emit("report", {"report": report})
            emit("done", {"run_id": run_id})
            return report
        finally:
            self._lock.release()

    def verify(self, before_run_id: str, on_event=None) -> dict:
        return self.diagnose(on_event, before_run_id=before_run_id)

    def _validate_baseline(self, before: dict):
        if not isinstance(before, dict) or before.get("schema_version") != "1.0" or not isinstance(before.get("run_id"), str):
            raise EnspError("invalid_baseline", "基线必须是本模块生成的诊断报告。")
        if before.get("config_fingerprint") != self.config.fingerprint or before.get("mode") != self.mode:
            raise EnspError("baseline_mismatch", "基线与当前设备、探测路径或 live/fixture 模式不一致，不能比较。")
        verification = before.get("verification")
        if not isinstance(verification, dict) or "passed" not in verification or not any(verification["passed"] is v for v in (True, False, None)):
            raise EnspError("invalid_baseline", "基线缺少有效的复检结果。")

    def _report(self, run_id: str, started: str, collected: list[dict]) -> dict:
        by_key = {(r["device"], r["command"]): r for r in collected}
        interface_command = f"display interface {self.config.interface}"
        interface_result = by_key[(self.config.switch.name, interface_command)]
        ping_command = commands(self.config)[self.config.probe.name][-1]
        ping_result = by_key[(self.config.probe.name, ping_command)]
        interface = parse_interface(interface_result["raw_output"], self.config.interface) if interface_result["status"] == "ok" else {"state": "unknown", "physical": None, "protocol": None}
        ping = parse_ping(ping_result["raw_output"]) if ping_result["status"] == "ok" else {"state": "unknown", "sent": None, "received": None, "loss_percent": None}
        state = interface["state"]
        repair_plan = None
        references = []
        if state == "admin_down" and self.config.expected_enabled:
            code, severity = "administratively_down", "critical"
            summary = "应启用的业务网口被配置为关闭。"
            repair_plan = {
                "execution": "manual_only", "confirmation": "确认这个网口不是因检修、安全隔离而主动停用。",
                "device": self.config.switch.name, "interface": self.config.interface,
                "commands": ["system-view", f"interface {self.config.interface}", "undo shutdown", "return"],
                "note": "在 eNSP 目标交换机控制台执行，再运行复检。不会自动保存设备配置。",
            }
            references = [dict(MANUAL_REFERENCE)]
        elif state == "admin_down":
            code, severity, summary = "intentionally_disabled", "info", "网口处于关闭状态；当前配置未声明它应启用，不建议自动恢复。"
        elif state == "error_down":
            code, severity, summary = "error_down", "critical", "网口因错误事件被保护性关闭，需要根据 down-cause 继续排查。"
        elif state == "down":
            code, severity, summary = "link_down", "critical", "网口链路未起来，不能据此判定为人为关闭。"
        elif state == "unknown" or ping["state"] == "unknown":
            code, severity, summary = "insufficient_evidence", "warning", "证据不完整，尚不能确认故障原因或通信恢复。"
        elif ping["state"] == "fail":
            code, severity, summary = "path_unreachable", "critical", "网口已 UP，但实验业务路径仍未通过连通性检查。"
        else:
            code, severity, summary = "healthy", "normal", "目标网口正常，实验业务路径连续三次探测成功。"

        if state in ("admin_down", "error_down", "down") or ping["state"] == "fail":
            passed = False
        elif state == "up" and ping["state"] == "pass":
            passed = True
        else:
            passed = None
        return {
            "schema_version": "1.0", "run_id": run_id, "mode": self.mode,
            "started_at": started, "finished_at": now(), "config_fingerprint": self.config.fingerprint,
            "target": {"device": self.config.switch.name, "interface": self.config.interface},
            "diagnosis": {"code": code, "severity": severity, "summary": summary, "source": "rule"},
            "observations": {"interface": interface, "ping": ping},
            "verification": {"passed": passed, "scope": "configured_virtual_business_path",
                             "probe_device": self.config.probe.name, "source": self.config.source,
                             "destination": self.config.destination,
                             "criteria": "目标端口物理/协议均 UP，且独立探测设备从指定业务 IP 发出 3 次 ping、收到 3 次回复、丢包率 0%。"},
            "repair_plan": repair_plan, "references": references, "commands": collected,
            "rag_context": {"query": "以太网接口 " + (interface["physical"] or "状态未知"),
                            "device_family": "Huawei S series", "evidence_run_id": run_id},
        }
