"""命令行：

    python -m engine list                         列出技能（含格式错误的）
    python -m engine run net-unreachable [--json] [--no-ai]   执行技能，打印采集、判定路径和报告
    python -m engine check "ping 1.1.1.1; rm -rf /"           只校验命令能否通过白名单（不执行）
"""

from __future__ import annotations

import argparse
import json
import sys

from . import executor
from .loader import list_skills
from .runner import run_skill

ICON = {"critical": "🔴 严重", "warning": "🟡 警告", "ok": "🟢 正常"}


def main() -> None:
    # Windows 终端默认用 GBK，报告里的 🔴🟡🟢 等符号会显示不了甚至报错退出；统一用 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m engine", description="诊断引擎")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出技能")
    run = sub.add_parser("run", help="执行技能")
    run.add_argument("skill")
    run.add_argument("--json", action="store_true", help="输出 done 事件的原始数据")
    run.add_argument("--no-ai", action="store_true", help="不调用模型做 AI 补充判定")
    check = sub.add_parser("check", help="校验命令是否在白名单")
    check.add_argument("cmd")
    check.add_argument("--switch", action="store_true", help="按交换机命令校验")
    args = parser.parse_args()

    if args.command == "list":
        for skill in list_skills():
            state = "可执行" if skill["valid"] else "格式错误：" + "；".join(skill["errors"])
            print(f"{skill['id']:<24} {skill['name']}（{state}）")
    elif args.command == "check":
        ok, reason = executor.check(args.cmd, "switch" if args.switch else "local")
        print("放行" if ok else f"{executor.REJECTED_TEXT}：{reason}")
        sys.exit(0 if ok else 1)
    else:
        try:
            for event, data in run_skill(args.skill, use_ai=not args.no_ai):
                if args.json:
                    if event == "done":
                        print(json.dumps(data, ensure_ascii=False, indent=2))
                    continue
                if event == "start":
                    print(f"== {data['name']}（{'本机真实执行' if data['live'] else '本机命令也用回放'}）\n")
                elif event == "collect":
                    print(f"$ {data['cmd']}    [{data['status']} · {data['duration']}s · {data['mode']}]")
                    print("  " + data["output"].replace("\n", "\n  ") + "\n")
                elif event == "rules":
                    print("== 规则树判定")
                    for rule in data["rules"]:
                        print(f"  {'✓' if rule['state'] == 'hit' else '–'} {rule['label']} → {rule['branch']}")
                elif event == "ai":
                    print(f"\n== AI 补充推理\n  {data['text']}")
                elif event == "report":
                    print(f"\n== 诊断报告（{data['elapsed']}s）")
                    for f in data["findings"]:
                        source = "规则树" if f["judged_by"] == "rule" else "AI 推理"
                        print(f"\n{ICON.get(f['severity'], f['severity'])}  {f['title']}（{source}）")
                        print(f"  现象：{f['symptom']}\n  根因：{f['root_cause']}")
                        for cmd in f["fix_commands"]:
                            print(f"    · {cmd}")
                        for s in f["sources"] or [{"label": "手册中未找到依据"}]:
                            print(f"  出处：{s['label']}")
                    for item in data["unresolved"]:
                        print(f"\n仍需人工确认：{item}")
        except ValueError as exc:
            print(exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
