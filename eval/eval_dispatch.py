"""调度器评测：在 eval/dispatch_cases.jsonl 上测 llm.qa.dispatch() 的分类准确率。

每道题的 expect 是可以接受的分类（greet / reject / clarify / answer），可以有多个。
最要紧的是「该回答的被拦下」（把手册问题判成拒答或追问），单独统计。

运行：.venv/bin/python eval/eval_dispatch.py
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import qa  # noqa: E402

CASES = Path(__file__).parent / "dispatch_cases.jsonl"
RESULTS = Path(__file__).parent / "results"


def main():
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows, latencies = [], []
    for case in cases:
        start = time.perf_counter()
        action = qa.dispatch(case["query"])["action"]
        latencies.append(time.perf_counter() - start)
        rows.append({**case, "got": action, "ok": action in case["expect"]})

    wrong = [r for r in rows if not r["ok"]]
    blocked = [r for r in rows if r["expect"] == ["answer"] and r["got"] != "answer"]
    for r in wrong:
        print(f"错  期望 {'/'.join(r['expect']):14} 实际 {r['got']:8} {r['query']}")
    summary = {
        "n": len(rows),
        "accuracy": sum(r["ok"] for r in rows) / len(rows),
        "by_expect": {k: f"{sum(r['ok'] for r in rows if r['expect'][0] == k)}/{v}"
                      for k, v in Counter(r["expect"][0] for r in rows).items()},
        "answer_blocked": len(blocked),  # 手册问题被判成拒答 / 追问 / 打招呼
        "latency_avg_s": sum(latencies) / len(latencies),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "dispatch.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                                           encoding="utf-8")


if __name__ == "__main__":
    main()
