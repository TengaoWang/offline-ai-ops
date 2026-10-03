"""评测技能路由 llm.route()：在测试集上计算准确率、JSON 合法率、各类别表现和平均耗时。

调用方式与队友实际使用的完全相同（本机 Ollama）。

用法：
  python eval/gen_data.py                       # 先生成测试数据
  python eval/eval_route.py                     # 默认模型 qwen3:8b
  python eval/eval_route.py --model qwen3:4b --tag qwen3-4b

结果写入 eval/results/<tag>.json，并在终端打印汇总与错误样例。
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from llm import config  # noqa: E402
from llm.router import route  # noqa: E402


def parse_skill(text: str):
    """从模型输出中解析 skill；返回 (skill, 是否为合法 JSON)。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    match = re.search(r"\{.*?\}", text, flags=re.S)
    if not match:
        return "<invalid>", False
    try:
        return json.loads(match.group(0)).get("skill", "<invalid>"), True
    except json.JSONDecodeError:
        return "<invalid>", False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=config.MODEL, help="Ollama 模型名，默认 qwen3:8b")
    parser.add_argument("--data", type=Path, default=HERE / "data" / "test.jsonl")
    parser.add_argument("--tag", default="qwen3-8b")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    rows = [json.loads(line) for line in open(args.data, encoding="utf-8")]
    if args.limit:
        rows = rows[: args.limit]

    records, latencies = [], []
    for row in rows:
        text = row["messages"][-2]["content"]  # 用户输入；系统提示词由 route() 自带
        gold = json.loads(row["messages"][-1]["content"])["skill"]
        start = time.perf_counter()
        output = route(text, model=args.model)["raw"]
        latencies.append(time.perf_counter() - start)
        pred, valid = parse_skill(output)
        records.append({"input": text, "gold": gold, "pred": pred, "valid_json": valid, "raw": output})

    total = len(records)
    correct = sum(r["pred"] == r["gold"] for r in records)
    per_class = defaultdict(lambda: [0, 0])
    for r in records:
        per_class[str(r["gold"])][1] += 1
        per_class[str(r["gold"])][0] += r["pred"] == r["gold"]
    confusion = Counter((str(r["gold"]), str(r["pred"])) for r in records if r["pred"] != r["gold"])

    summary = {
        "tag": args.tag,
        "model": args.model,
        "n": total,
        "accuracy": round(correct / total, 4),
        "valid_json_rate": round(sum(r["valid_json"] for r in records) / total, 4),
        "per_class_accuracy": {k: round(c / n, 4) for k, (c, n) in sorted(per_class.items())},
        "avg_latency_s": round(sum(latencies) / total, 3),
        "top_confusions": [{"gold": g, "pred": p, "count": c} for (g, p), c in confusion.most_common(10)],
    }

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / f"{args.tag}.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n错误样例：")
    for r in [r for r in records if r["pred"] != r["gold"]][:15]:
        print(f"  [{r['gold']} -> {r['pred']}] {r['input']}  | raw={r['raw']!r}")


if __name__ == "__main__":
    main()
