"""评测 T1「技能路由」：在测试集上计算准确率、JSON 合法率、各类别表现和平均耗时。

用法：
  # 基线（MLX，未微调）
  python finetune/eval.py --tag base
  # 微调后（MLX）
  python finetune/eval.py --adapter finetune/adapters/qwen3-8b-t1 --tag lora
  # 交付版本：通过 Ollama 调用（与队友实际使用的方式完全相同）
  python finetune/eval.py --backend ollama --model qwen3:8b --tag ollama-base

结果写入 finetune/results/<tag>.json，并在终端打印汇总与错误样例。
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
    parser.add_argument("--backend", choices=["mlx", "ollama"], default="mlx")
    parser.add_argument("--model", default=None,
                        help="mlx 默认 mlx-community/Qwen3-8B-4bit；ollama 默认 qwen3:8b")
    parser.add_argument("--adapter", default=None, help="仅 mlx：LoRA adapter 目录")
    parser.add_argument("--data", type=Path, default=HERE / "data" / "test.jsonl")
    parser.add_argument("--tag", default="base")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    args.model = args.model or ("qwen3:8b" if args.backend == "ollama" else "mlx-community/Qwen3-8B-4bit")

    if args.backend == "mlx":
        from mlx_lm import generate, load

        model, tokenizer = load(args.model, adapter_path=args.adapter)

        def predict(prompt_msgs):
            prompt = tokenizer.apply_chat_template(
                prompt_msgs, add_generation_prompt=True, tokenize=False, enable_thinking=False
            )
            return generate(model, tokenizer, prompt=prompt, max_tokens=32, verbose=False)
    else:
        from llm.router import route

        def predict(prompt_msgs):
            # route() 自带同一份系统提示词，这里只传用户输入
            return route(prompt_msgs[-1]["content"], model=args.model)["raw"]

    rows = [json.loads(line) for line in open(args.data, encoding="utf-8")]
    if args.limit:
        rows = rows[: args.limit]

    records, latencies = [], []
    for row in rows:
        prompt_msgs, gold_msg = row["messages"][:-1], row["messages"][-1]
        gold = json.loads(gold_msg["content"])["skill"]
        start = time.perf_counter()
        output = predict(prompt_msgs)
        latencies.append(time.perf_counter() - start)
        pred, valid = parse_skill(output)
        records.append({"input": prompt_msgs[-1]["content"], "gold": gold, "pred": pred,
                        "valid_json": valid, "raw": output})

    total = len(records)
    correct = sum(r["pred"] == r["gold"] for r in records)
    per_class = defaultdict(lambda: [0, 0])
    for r in records:
        per_class[str(r["gold"])][1] += 1
        per_class[str(r["gold"])][0] += r["pred"] == r["gold"]
    confusion = Counter((str(r["gold"]), str(r["pred"])) for r in records if r["pred"] != r["gold"])

    summary = {
        "tag": args.tag,
        "backend": args.backend,
        "model": args.model,
        "adapter": args.adapter,
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
