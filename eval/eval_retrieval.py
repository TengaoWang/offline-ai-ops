"""检索评测：在 eval/retrieval_cases.jsonl 上测 llm.retrieve 的准确率和耗时。

标准答案写的是手册章节号（如 "8.2"），脚本按 PDF 书签换成页码范围；
检索结果里任意一段的页码落在范围内，就算命中。不需要调用大模型。

运行：.venv/bin/python eval/eval_retrieval.py --tag baseline --mode bm25
     .venv/bin/python eval/eval_retrieval.py --tag hybrid-bge-m3 --mode hybrid --embed-model bge-m3
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import config, rag  # noqa: E402

CASES = Path(__file__).parent / "retrieval_cases.jsonl"
RESULTS = Path(__file__).parent / "results"
HANDBOOK = "华为S系列园区交换机维护宝典.pdf"
TOP_N = 10  # 统计 MRR 时看前多少名


def section_pages(pdf_path: Path) -> dict[str, tuple[int, int]]:
    """章节号 -> (起始页, 结束页)。结束页 = 下一个同级或更高级章节的起始页
    （章节常在页面中间结束，下一节开始的那一页也可能有本节内容）。"""
    toc = pymupdf.open(pdf_path).get_toc()
    ranges = {}
    for i, (level, title, start) in enumerate(toc):
        number = title.split(" ", 1)[0]
        end = start
        for next_level, _, next_start in toc[i + 1:]:
            if next_level <= level:
                end = max(start, next_start)
                break
        ranges.setdefault(number, (start, end))
    return ranges


def first_hit_rank(results: list[dict], gold: list[tuple[int, int]]) -> int | None:
    for rank, r in enumerate(results, start=1):
        if r["file"] == HANDBOOK and r["page"] and any(a <= r["page"] <= b for a, b in gold):
            return rank
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="baseline", help="结果文件名")
    parser.add_argument("--mode", default=config.RETRIEVE_MODE, choices=["bm25", "vector", "hybrid"])
    parser.add_argument("--embed-model", default=config.EMBED_MODEL)
    args = parser.parse_args()
    config.EMBED_MODEL = args.embed_model

    ranges = section_pages(config.DOCS_DIR / HANDBOOK)
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]

    rows, latencies = [], []
    for case in cases:
        missing = [s for s in case["gold"] if s not in ranges]
        if missing:
            sys.exit(f"{case['id']}：手册目录里找不到章节 {missing}")
        gold = [ranges[s] for s in case["gold"]]
        start = time.perf_counter()
        results = rag.retrieve(case["query"], k=TOP_N, mode=args.mode)
        if results and results[0]["mode"] != args.mode:
            sys.exit(f"实际检索方式是 {results[0]['mode']}，不是 {args.mode}：请先运行 python -m llm embed {args.embed_model}")
        latencies.append(time.perf_counter() - start)
        rank = first_hit_rank(results, gold) if gold else None
        rows.append({
            "id": case["id"], "type": case["type"], "query": case["query"],
            "gold": case["gold"], "rank": rank,
            "top_score": results[0]["score"] if results else None,
            "max_vec_score": max((r["vec_score"] for r in results if r["vec_score"] is not None), default=None),
            "top3": [f"P{r['page']} {r['section'].split(' > ')[-1]}" for r in results[:3]],
        })

    answerable = [r for r in rows if r["type"] != "unanswerable"]

    def hit(rs, k):
        return sum(1 for r in rs if r["rank"] and r["rank"] <= k) / len(rs) if rs else 0.0

    summary = {
        "mode": args.mode,
        "embed_model": args.embed_model if args.mode != "bm25" else None,
        "n": len(answerable),
        "hit@1": hit(answerable, 1),
        "hit@3": hit(answerable, 3),
        "hit@5": hit(answerable, 5),
        "mrr": sum(1 / r["rank"] for r in answerable if r["rank"]) / len(answerable),
        "hit@3_by_type": {t: hit([r for r in answerable if r["type"] == t], 3)
                          for t in ("fr2", "agent", "formal", "colloquial")},
        "latency_p50_s": statistics.median(latencies),
        "latency_p95_s": sorted(latencies)[int(0.95 * (len(latencies) - 1))],
    }

    print(f"{'id':5} {'类型':12} {'名次':>4}  问题")
    for r in rows:
        rank = "-" if r["type"] == "unanswerable" else (r["rank"] or "未中")
        print(f"{r['id']:5} {r['type']:12} {str(rank):>4}  {r['query']}")
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"retrieval-{args.tag}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n已保存：{out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
