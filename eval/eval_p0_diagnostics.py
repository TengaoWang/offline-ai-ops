"""Persist repeatable P0 diagnostic evidence without disguising simulation as real execution."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import SkillEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    engine = SkillEngine(ROOT / "skills", ROOT / "runtime", ROOT)
    scenarios = [
        ("disk_real", "disk-full", "real", False, "本机磁盘容量只读检查"),
        ("disk_rule", "disk-full", "simulation", False, "模拟磁盘容量告警"),
        ("service_partial_failure", "service-down", "simulation", False, "模拟服务状态采集部分失败"),
        ("log_rule", "log-audit", "simulation", False, "模拟日志审计采集"),
        ("network_ai", "net-unreachable", "simulation", True, "模拟网络不通且缺少交换机侧实时输出"),
    ]
    rows = []
    for name, skill, mode, enable_ai, issue in scenarios:
        result = engine.run(skill, mode=mode, issue=issue, enable_ai=enable_ai)
        published_sourced = all(bool(item.get("sources")) for item in result["findings"])
        row = {"name": name, "passed": bool(result["collected"]) and published_sourced,
               "has_ai": any(item.get("judged_by") == "ai" for item in result["findings"]),
               "has_partial_failure": any(item.get("status") != "success" for item in result["collected"]),
               "result": result}
        rows.append(row)
        print(f"{name:24} {'PASS' if row['passed'] else 'FAIL'} {result['timing']['total_s']}s", flush=True)
    summary = {
        "passed": sum(row["passed"] for row in rows), "total": len(rows),
        "real_runs": sum(row["result"]["execution_mode"] == "real" for row in rows),
        "ai_scenarios": sum(row["has_ai"] for row in rows),
        "partial_failure_scenarios": sum(row["has_partial_failure"] for row in rows),
        "all_published_findings_sourced": all(row["passed"] for row in rows),
    }
    output_dir = ROOT / "eval" / "results"
    output_dir.mkdir(exist_ok=True)
    output = output_dir / f"p0-diagnostics-{args.tag}.json"
    output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(output)
    raise SystemExit(0 if summary["passed"] == summary["total"] and summary["real_runs"] >= 1 else 1)


if __name__ == "__main__":
    main()
