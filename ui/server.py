"""Local HTTP server for the offline AI ops frontend.

The server intentionally uses only the Python standard library plus the
existing llm package so it can run from the portable box without a frontend
toolchain or CDN access.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sqlite3
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from llm import SKILLS, ask, chat, config, health, ingest, route

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "ui" / "static"
SKILLS_DIR = ROOT / "skills"

DEFAULT_SKILLS: dict[str, dict[str, Any]] = {
    "net-unreachable": {
        "name": "网络连通排查",
        "description": "网关、服务器、交换机端口、VLAN 方向的一键排查。",
        "command_count": 4,
    },
    "disk-full": {
        "name": "磁盘存储排查",
        "description": "分区空间、inode、日志目录和大文件定位。",
        "command_count": 4,
    },
    "service-down": {
        "name": "服务进程排查",
        "description": "服务状态、端口监听、进程崩溃和重启原因排查。",
        "command_count": 4,
    },
    "log-audit": {
        "name": "日志审计排查",
        "description": "异常登录、配置变更、错误日志和白名单拦截演示。",
        "command_count": 4,
    },
}


DEMO_RUNS: dict[str, dict[str, Any]] = {
    "net-unreachable": {
        "skill": "net-unreachable",
        "commands": [
            {
                "cmd": "ping 192.168.10.20 -c 2",
                "status": "failed",
                "duration": 2.1,
                "output": "2 packets transmitted, 0 received, 100% packet loss",
            },
            {
                "cmd": "ping 192.168.10.1 -c 2",
                "status": "success",
                "duration": 0.8,
                "output": "64 bytes from 192.168.10.1: icmp_seq=1 ttl=64 time=0.8 ms",
            },
            {
                "cmd": "ipconfig | findstr 192.168",
                "status": "success",
                "duration": 0.4,
                "output": "IPv4 Address. . . . . . . . . . . : 192.168.10.15",
            },
            {
                "cmd": "ping 192.168.10.21 -c 2",
                "status": "success",
                "duration": 1.7,
                "output": "64 bytes from 192.168.10.21: icmp_seq=1 ttl=64 time=2.1 ms",
            },
        ],
        "rules": [
            {"label": "目标 IP 100% 丢包", "state": "hit", "branch": "网络不可达"},
            {"label": "网关可达", "state": "hit", "branch": "本机链路正常"},
            {"label": "本机 IP 正常获取", "state": "hit", "branch": "非 DHCP 问题"},
            {"label": "管理口可达、业务口不可达", "state": "hit", "branch": "端口/VLAN 层故障"},
        ],
        "ai_reasoning": "管理口可达但业务口不可达，服务器硬件未宕机；结合手册出处，优先怀疑交换机端口 VLAN 配置异常或端口 err-down 后未恢复。",
        "findings": [
            {
                "severity": "critical",
                "title": "MES 服务器业务网卡不可达",
                "symptom": "ping 192.168.10.20 100% 丢包；网关和服务器管理口均可达。",
                "root_cause": "交换机 GE0/0/8 端口 VLAN 配置异常，应属 VLAN 10。",
                "fix_commands": [
                    "console 线连接 S5700",
                    "system-view",
                    "interface GigabitEthernet 0/0/8",
                    "port link-type access",
                    "port default vlan 10",
                    "display vlan 10",
                ],
                "judged_by": "rule",
                "rule_path": ["目标 IP 100% 丢包", "网关可达", "管理口可达、业务口不可达"],
                "sources": [
                    {
                        "label": "《S5700 产品文档》§3.2.1 VLAN 配置 P47",
                        "text": "Access 端口应加入业务 VLAN 后再验证端口 VLAN 成员关系。",
                    },
                    {
                        "label": "《S5700 产品文档》§4.1.3 端口排障 P112",
                        "text": "业务不可达但管理口正常时，应检查端口状态、VLAN 归属与链路类型。",
                    },
                ],
            },
            {
                "severity": "ok",
                "title": "本机到网关链路正常",
                "symptom": "网关 192.168.10.1 响应正常。",
                "root_cause": "未发现本机链路层异常。",
                "fix_commands": ["无需执行写操作。"],
                "judged_by": "rule",
                "rule_path": ["网关可达"],
                "sources": [
                    {
                        "label": "《S5700 产品文档》§4.1.1 连通性检查 P108",
                        "text": "先确认本机到网关链路，再继续定位业务网段。",
                    }
                ],
            },
            {
                "severity": "warning",
                "title": "需要现场确认端口灯与配置一致",
                "symptom": "规则树已定位到端口/VLAN 分支，但无法在当前主机直接读取交换机配置。",
                "root_cause": "缺少交换机侧 display 输出。",
                "fix_commands": ["display interface brief", "display vlan 10"],
                "judged_by": "ai",
                "rule_path": ["规则未覆盖交换机侧实时状态", "AI 补充判定"],
                "sources": [
                    {
                        "label": "《S5700 产品文档》§4.1.3 端口排障 P112",
                        "text": "端口故障定位需要结合 display interface 与 VLAN 成员信息。",
                    }
                ],
            },
        ],
        "unresolved": [],
        "elapsed": 12.4,
    },
    "disk-full": {
        "skill": "disk-full",
        "commands": [
            {"cmd": "df -h", "status": "success", "duration": 0.3, "output": "/var 237G 236G 0.2G 100% /var"},
            {"cmd": "df -i", "status": "success", "duration": 0.2, "output": "/var inode 使用率 12%"},
            {"cmd": "du -sh /var/log", "status": "success", "duration": 2.4, "output": "89G /var/log"},
            {"cmd": "ls -lhS /var/log | head -5", "status": "success", "duration": 0.5, "output": "42G syslog.1\n2.1G kern.log.1"},
        ],
        "rules": [
            {"label": "分区使用率 100% > 90%", "state": "hit", "branch": "磁盘告警"},
            {"label": "inode 使用率正常", "state": "hit", "branch": "排除小文件堆积"},
            {"label": "/var/log 占比最大", "state": "hit", "branch": "日志目录分支"},
        ],
        "ai_reasoning": "空间耗尽集中在日志目录，inode 正常，最可能是日志轮转失效或异常日志增长。",
        "findings": [
            {
                "severity": "warning",
                "title": "/var/log 分区空间耗尽",
                "symptom": "/var 使用率 100%，日志目录占 89G。",
                "root_cause": "日志轮转失效，syslog.1 单文件 42G。",
                "fix_commands": ["gzip /var/log/syslog.1", "检查 /etc/logrotate.d/ 策略", "重启相关日志服务前先确认进程句柄"],
                "judged_by": "rule",
                "rule_path": ["磁盘告警", "排除小文件堆积", "日志目录分支"],
                "sources": [
                    {
                        "label": "《Linux 运维手册》§7.3 日志管理 P112",
                        "text": "大日志文件应优先压缩或轮转，直接删除可能因进程持有句柄而不释放空间。",
                    }
                ],
            },
            {
                "severity": "ok",
                "title": "inode 未耗尽",
                "symptom": "inode 使用率 12%。",
                "root_cause": "不是小文件数量过多导致。",
                "fix_commands": ["无需处理 inode。"],
                "judged_by": "rule",
                "rule_path": ["inode 使用率正常"],
                "sources": [
                    {
                        "label": "《Linux 运维手册》§7.2 文件系统检查 P105",
                        "text": "空间与 inode 需要分别检查，二者可能独立耗尽。",
                    }
                ],
            },
            {
                "severity": "warning",
                "title": "需要验证日志增长源",
                "symptom": "syslog.1 体积异常。",
                "root_cause": "可能存在持续刷屏的服务或内核错误。",
                "fix_commands": ["tail -n 100 /var/log/syslog", "systemctl status rsyslog"],
                "judged_by": "ai",
                "rule_path": ["规则树定位到日志目录", "AI 补充定位增长源"],
                "sources": [],
            },
        ],
        "unresolved": ["日志增长源需结合最新 syslog 内容继续确认。"],
        "elapsed": 9.8,
    },
    "service-down": {
        "skill": "service-down",
        "commands": [
            {"cmd": "systemctl status nginx", "status": "failed", "duration": 1.0, "output": "nginx.service: Failed with result 'exit-code'"},
            {"cmd": "ss -tlnp | grep :80", "status": "failed", "duration": 0.4, "output": "未发现 80 端口监听"},
            {"cmd": "journalctl -u nginx -n 50", "status": "success", "duration": 1.8, "output": "bind() to 0.0.0.0:80 failed (98: Address already in use)"},
            {"cmd": "ps aux | grep nginx", "status": "success", "duration": 0.3, "output": "nginx master process 未运行"},
        ],
        "rules": [
            {"label": "服务状态 failed", "state": "hit", "branch": "服务异常"},
            {"label": "80 端口未监听", "state": "hit", "branch": "业务不可用"},
            {"label": "日志含 bind failed", "state": "hit", "branch": "端口冲突或配置异常"},
        ],
        "ai_reasoning": "服务失败且端口未监听，日志提示 bind 失败，应先确认端口占用和配置文件语法。",
        "findings": [
            {
                "severity": "critical",
                "title": "nginx 服务未启动",
                "symptom": "systemctl 显示 failed，80 端口未监听。",
                "root_cause": "配置或端口绑定失败导致服务退出。",
                "fix_commands": ["nginx -t", "ss -tlnp | grep :80", "systemctl restart nginx"],
                "judged_by": "rule",
                "rule_path": ["服务状态 failed", "80 端口未监听", "日志含 bind failed"],
                "sources": [
                    {
                        "label": "《Linux 运维手册》§5.2 服务启动失败 P88",
                        "text": "服务启动失败时先检查配置语法与端口占用。",
                    }
                ],
            },
            {
                "severity": "warning",
                "title": "需要确认端口占用来源",
                "symptom": "日志提示 bind failed。",
                "root_cause": "可能是旧进程、其他 Web 服务或配置重复监听。",
                "fix_commands": ["ss -tlnp | grep :80"],
                "judged_by": "ai",
                "rule_path": ["规则树命中服务失败", "AI 补充端口占用排查"],
                "sources": [],
            },
            {
                "severity": "ok",
                "title": "进程残留未发现",
                "symptom": "ps 未发现 nginx master process。",
                "root_cause": "当前无 nginx 主进程残留。",
                "fix_commands": ["无需清理 nginx 残留进程。"],
                "judged_by": "rule",
                "rule_path": ["ps 输出未发现主进程"],
                "sources": [
                    {
                        "label": "《Linux 运维手册》§5.1 进程检查 P84",
                        "text": "服务状态应结合 systemd、端口与进程列表交叉确认。",
                    }
                ],
            },
        ],
        "unresolved": [],
        "elapsed": 11.2,
    },
    "log-audit": {
        "skill": "log-audit",
        "commands": [
            {"cmd": "last -n 10", "status": "success", "duration": 0.6, "output": "admin pts/0 192.168.10.18 Fri 17:21"},
            {"cmd": "grep -i failed /var/log/auth.log | tail -20", "status": "success", "duration": 0.9, "output": "Failed password for root from 10.0.0.9"},
            {"cmd": "ping 1.1.1.1; rm -rf /", "status": "rejected", "duration": 0.0, "output": "该命令不在白名单，已拒绝"},
            {"cmd": "journalctl -p err -n 20", "status": "success", "duration": 1.2, "output": "sudo: admin : TTY=pts/0 ; COMMAND=/usr/bin/vim /etc/hosts"},
        ],
        "rules": [
            {"label": "存在失败登录记录", "state": "hit", "branch": "登录异常"},
            {"label": "命令包含注入分隔符", "state": "hit", "branch": "白名单拦截"},
            {"label": "sudo 修改配置痕迹", "state": "hit", "branch": "配置变更审计"},
        ],
        "ai_reasoning": "日志显示失败登录与配置变更痕迹，建议先保留证据，再核对变更窗口与授权记录。",
        "findings": [
            {
                "severity": "warning",
                "title": "发现失败登录尝试",
                "symptom": "auth.log 中出现 root 登录失败记录。",
                "root_cause": "可能是误输密码，也可能是未授权访问尝试。",
                "fix_commands": ["保存 auth.log 片段", "核对来源 IP 10.0.0.9", "确认是否需要临时封禁来源"],
                "judged_by": "rule",
                "rule_path": ["存在失败登录记录"],
                "sources": [
                    {
                        "label": "《Linux 安全审计手册》§2.4 登录审计 P31",
                        "text": "失败登录应记录来源、账号、时间，并与维护窗口对齐核查。",
                    }
                ],
            },
            {
                "severity": "ok",
                "title": "危险命令已被拦截",
                "symptom": "包含分号和删除操作的命令未执行。",
                "root_cause": "白名单执行器按安全策略拒绝。",
                "fix_commands": ["无需执行写操作。"],
                "judged_by": "rule",
                "rule_path": ["命令包含注入分隔符", "白名单拦截"],
                "sources": [
                    {
                        "label": "《安全执行规范》§1.1 白名单 P5",
                        "text": "执行器必须拒绝分号、管道、反引号等注入风险参数。",
                    }
                ],
            },
            {
                "severity": "warning",
                "title": "存在配置变更痕迹",
                "symptom": "sudo 日志显示 admin 编辑 /etc/hosts。",
                "root_cause": "需要与变更单或现场操作人员确认。",
                "fix_commands": ["记录 sudo 日志", "diff /etc/hosts 与备份文件"],
                "judged_by": "ai",
                "rule_path": ["sudo 修改配置痕迹", "AI 补充审计建议"],
                "sources": [],
            },
        ],
        "unresolved": ["admin 的操作是否授权需人工确认。"],
        "elapsed": 8.6,
    },
}


def _json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _fallback_title(text: str, skill_id: str | None, locale: str) -> str:
    english = locale == "en"
    is_mes = bool(re.search(r"mes", text, re.I))
    titles = {
        "net-unreachable": ("MES network connectivity issue" if is_mes else "Network connectivity issue", "MES 业务网连通异常" if is_mes else "网络连通异常"),
        "disk-full": ("Server disk space alert", "服务器磁盘空间告警"),
        "service-down": ("Service startup failure", "服务启动故障"),
        "log-audit": ("Log audit · suspicious activity", "日志审计 · 异常活动"),
    }
    if skill_id in titles:
        return titles[skill_id][0 if english else 1]
    cleaned = re.sub(r"^(一键体检[:：]|run selected skill[:：])", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned)
    limit = 52 if english else 24
    return (cleaned[:limit].rstrip("，。；;,. ") + ("…" if len(cleaned) > limit else "")) or ("New troubleshooting chat" if english else "新的排障会话")


def _make_title(text: str, skill_id: str | None, locale: str) -> tuple[str, str]:
    fallback = _fallback_title(text, skill_id, locale)
    if config.MOCK:
        return fallback, "fallback"
    language = "English" if locale == "en" else "Simplified Chinese"
    schema = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"], "additionalProperties": False}
    try:
        response = chat(
            [
                {"role": "system", "content": f"Summarize the infrastructure troubleshooting issue as a concise {language} chat title. Return a short title, without quotation marks, with no more than 12 words."},
                {"role": "user", "content": f"Selected skill: {skill_id or 'automatic routing'}\nIssue: {text[:2000]}"},
            ],
            schema=schema,
        )
        title = str(json.loads(response).get("title", "")).strip().strip("\"'` ")
        if title and len(title) <= 64 and "\n" not in title:
            return title, "model"
    except Exception:
        pass
    return fallback, "fallback"


def _safe_skill_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or f"saved-skill-{int(time.time())}"


def _read_heading(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if text.startswith("#"):
            return text.lstrip("#").strip() or None
    return None


def _command_count(skill_dir: Path) -> int:
    collect = skill_dir / "collect.yaml"
    if not collect.exists():
        return 0
    return sum(1 for line in collect.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip().startswith("-"))


def list_skill_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if SKILLS_DIR.exists():
        for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
            skill_id = skill_dir.name
            default = DEFAULT_SKILLS.get(skill_id, {})
            cards.append(
                {
                    "id": skill_id,
                    "name": _read_heading(skill_dir / "SKILL.md") or default.get("name") or skill_id,
                    "description": default.get("description") or "本地 skills/ 目录识别到的技能包。",
                    "command_count": _command_count(skill_dir),
                    "source": "skills/",
                }
            )
    known = {card["id"] for card in cards}
    for skill_id in SKILLS:
        if skill_id in known:
            continue
        default = DEFAULT_SKILLS[skill_id]
        cards.append({"id": skill_id, "source": "demo", **default})
    return cards


def index_samples(limit: int = 3) -> list[dict[str, Any]]:
    if not config.INDEX_PATH.exists():
        return []
    with sqlite3.connect(config.INDEX_PATH) as db:
        rows = db.execute(
            "SELECT file, page, section, text FROM chunks ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "file": file,
            "page": page,
            "section": section,
            "text": text[:360],
        }
        for file, page, section, text in rows
    ]


def extended_health() -> dict[str, Any]:
    try:
        status = health()
    except Exception as exc:  # pragma: no cover - defensive for broken local indexes
        status = {"mock": config.MOCK, "ollama": False, "model": False, "index": False, "chunks": 0, "error": str(exc)}
    manual_files = []
    if config.DOCS_DIR.exists():
        manual_files = [
            {"name": p.name, "size": p.stat().st_size}
            for p in sorted(config.DOCS_DIR.iterdir())
            if p.suffix.lower() in {".pdf", ".md", ".txt"}
        ]
    return {
        **status,
        "model_name": config.MODEL,
        "docs_dir": str(config.DOCS_DIR),
        "index_path": str(config.INDEX_PATH),
        "manual_files": manual_files,
        "skills_count": len(list_skill_cards()),
    }


def _multipart_file(headers: str, body: bytes) -> tuple[str, bytes] | None:
    disposition = next((line for line in headers.splitlines() if line.lower().startswith("content-disposition:")), "")
    match = re.search(r'filename="([^"]+)"', disposition)
    if not match:
        return None
    filename = Path(match.group(1)).name
    return filename, body.rstrip(b"\r\n")


def parse_multipart(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    match = re.search(r"boundary=(.+)", content_type)
    if not match:
        return []
    boundary = match.group(1).strip().strip('"')
    marker = ("--" + boundary).encode()
    files: list[tuple[str, bytes]] = []
    for raw_part in body.split(marker):
        part = raw_part.strip()
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip()
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, payload = part.split(b"\r\n\r\n", 1)
        parsed = _multipart_file(raw_headers.decode("utf-8", "replace"), payload)
        if parsed:
            files.append(parsed)
    return files


def build_skill_draft(name: str, run: dict[str, Any]) -> dict[str, str]:
    title = name.strip() or "现场沉淀技能"
    commands = [item["cmd"] for item in run.get("commands", []) if item.get("status") != "rejected"]
    rules = run.get("rules", [])
    sources = [
        source
        for finding in run.get("findings", [])
        for source in finding.get("sources", [])
    ]
    collect_yaml = "commands:\n" + "".join(f'  - "{cmd}"\n' for cmd in commands)
    rules_yaml = "rules:\n" + "".join(
        f'  - id: r{index}\n    if: "{rule.get("label", "待补充条件")}"\n    then: "{rule.get("branch", "待补充分支")}"\n'
        for index, rule in enumerate(rules, 1)
    )
    refs_yaml = "refs:\n" + "".join(
        f'  - source: "{source.get("label", "手册中未找到依据")}"\n'
        for source in sources
    )
    skill_md = (
        f"# {title}\n\n"
        "适用于本次诊断中沉淀出的现场排查流程。\n\n"
        "## 采集命令\n\n"
        + "\n".join(f"- `{cmd}`" for cmd in commands)
        + "\n\n## 安全边界\n\n只执行白名单内只读采集命令；写操作仅作为报告建议展示。\n"
    )
    return {
        "SKILL.md": skill_md,
        "collect.yaml": collect_yaml,
        "rules.yaml": rules_yaml,
        "refs.yaml": refs_yaml,
    }


class UIHandler(BaseHTTPRequestHandler):
    server_version = "OfflineAIOpsUI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[ui] {self.address_string()} - {fmt % args}")

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = _json(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(extended_health())
        elif parsed.path == "/api/skills":
            self._send_json({"skills": list_skill_cards()})
        elif parsed.path == "/api/manuals/samples":
            self._send_json({"samples": index_samples()})
        elif parsed.path == "/api/diagnose/stream":
            query = urllib.parse.parse_qs(parsed.query)
            self._diagnose_stream(query.get("skill", ["net-unreachable"])[0])
        elif parsed.path.startswith("/api/"):
            self._send_json({"error": "not_found"}, status=404)
        else:
            self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/route":
                payload = self._read_json_body()
                self._send_json(route(str(payload.get("text", ""))))
            elif parsed.path == "/api/title":
                payload = self._read_json_body()
                title, source = _make_title(
                    str(payload.get("text", "")),
                    str(payload.get("skill", "")) or None,
                    "en" if payload.get("locale") == "en" else "zh-CN",
                )
                self._send_json({"title": title, "source": source})
            elif parsed.path == "/api/ask":
                payload = self._read_json_body()
                question = str(payload.get("question", ""))
                self._send_json(ask(question))
            elif parsed.path == "/api/manuals/upload":
                self._handle_upload()
            elif parsed.path == "/api/manuals/ingest":
                stats = ingest()
                self._send_json({"ok": True, "stats": stats, "samples": index_samples()})
            elif parsed.path == "/api/save-skill":
                self._handle_save_skill()
            else:
                self._send_json({"error": "not_found"}, status=404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _serve_static(self, path: str) -> None:
        requested = urllib.parse.unquote(path)
        if requested == "/":
            requested = "/index.html"
        static_root = STATIC_DIR.resolve()
        target = (STATIC_DIR / requested.lstrip("/")).resolve()
        if not target.is_file() or static_root not in [target, *target.parents]:
            self._send_json({"error": "not_found"}, status=404)
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, event: str, data: Any) -> None:
        self.wfile.write(f"event: {event}\n".encode("utf-8"))
        self.wfile.write(b"data: ")
        self.wfile.write(_json(data))
        self.wfile.write(b"\n\n")
        self.wfile.flush()

    def _diagnose_stream(self, skill_id: str) -> None:
        run = DEMO_RUNS.get(skill_id) or DEMO_RUNS["net-unreachable"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self._send_sse("start", {"skill": run["skill"], "demo": True})
            for index, command in enumerate(run["commands"], 1):
                time.sleep(0.2)
                self._send_sse("collect", {"index": index, **command})
            time.sleep(0.2)
            self._send_sse("rules", {"rules": run["rules"]})
            time.sleep(0.2)
            self._send_sse("ai", {"text": run["ai_reasoning"], "source": "AI 补充推理"})
            time.sleep(0.2)
            self._send_sse("report", {"findings": run["findings"], "unresolved": run["unresolved"], "elapsed": run["elapsed"]})
            self._send_sse("done", run)
        except BrokenPipeError:
            return

    def _handle_upload(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        content_type = self.headers.get("Content-Type", "")
        files = parse_multipart(content_type, self.rfile.read(length))
        if not files:
            self._send_json({"error": "未收到手册文件"}, status=400)
            return
        saved = []
        config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
        for filename, data in files:
            suffix = Path(filename).suffix.lower()
            if suffix not in {".pdf", ".md", ".txt"}:
                self._send_json({"error": f"不支持的文件类型：{filename}"}, status=400)
                return
            target = config.DOCS_DIR / filename
            target.write_bytes(data)
            saved.append({"name": filename, "size": len(data)})
        self._send_json({"ok": True, "saved": saved})

    def _handle_save_skill(self) -> None:
        payload = self._read_json_body()
        name = str(payload.get("name", "")).strip() or "现场沉淀技能"
        slug = _safe_skill_slug(str(payload.get("slug") or name))
        run = payload.get("run") or DEMO_RUNS["net-unreachable"]
        target = SKILLS_DIR / slug
        if target.exists():
            target = SKILLS_DIR / f"{slug}-{int(time.time())}"
        target.mkdir(parents=True, exist_ok=False)
        for filename, text in build_skill_draft(name, run).items():
            (target / filename).write_text(text, encoding="utf-8")
        self._send_json({"ok": True, "skill_id": target.name, "path": str(target), "skills": list_skill_cards()})


def self_check() -> dict[str, Any]:
    files = ["index.html", "styles.css", "app.js"]
    missing = [name for name in files if not (STATIC_DIR / name).exists()]
    external_refs: list[str] = []
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    for name in files:
        path = STATIC_DIR / name
        if not path.exists():
            continue
        for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for match in re.finditer(r"(?:https?:)?//[^\s\"'<>]+", line):
                reference = match.group(0).rstrip(".,;)")
                parsed = urllib.parse.urlsplit(reference if reference.startswith("http") else "https:" + reference)
                if parsed.hostname not in local_hosts:
                    external_refs.append(f"{name}:{index}:{reference}")
    return {
        "ok": not missing and not external_refs,
        "missing": missing,
        "external_refs": external_refs,
        "skills": len(list_skill_cards()),
        "samples": len(index_samples()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline-ai-ops local web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="run static self-check and exit")
    args = parser.parse_args()
    if args.check:
        result = self_check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    server = ThreadingHTTPServer((args.host, args.port), UIHandler)
    print(f"offline-ai-ops UI running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
