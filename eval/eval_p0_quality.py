"""Run the independent P0 answer/no-answer/multi-turn gate against the real local stack."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import answer, health


CASES = ROOT / "eval" / "p0_quality_cases.json"
RESULTS = ROOT / "eval" / "results"


def source_text(result: dict) -> str:
    return "\n".join([result.get("answer", ""), *[item.get("text", "") for item in result.get("citations", [])]])


def cited(result: dict) -> bool:
    return bool(result.get("citations")) and all(
        item.get("file") and item.get("section") and item.get("page") is not None and item.get("text")
        for item in result["citations"]
    )


def answerable(case: dict) -> dict:
    try:
        result = answer(case["question"])
    except Exception as exc:
        return {"id": case["id"], "question": case["question"], "passed": False,
                "error": {"type": type(exc).__name__, "message": str(exc)}, "result": None}
    haystack = source_text(result).lower()
    answer_text = result.get("answer", "").strip()
    useful = (result.get("answer_type") in {"generated", "extracted"} and cited(result)
              and (result.get("answer_type") == "extracted" or not result.get("unsupported_commands"))
              and len(answer_text) >= 20 and not answer_text.endswith(("：", ":"))
              and any(term.lower() in haystack for term in case["expect_any"]))
    return {"id": case["id"], "question": case["question"], "passed": useful, "result": result}


def unanswerable(case: dict) -> dict:
    try:
        result = answer(case["question"])
    except Exception as exc:
        return {"id": case["id"], "category": case["category"], "question": case["question"],
                "passed": False, "manual_review": False,
                "error": {"type": type(exc).__name__, "message": str(exc)}, "result": None}
    # generated is a published substantive answer. Extracted is a verbatim, cited fallback and is
    # retained for manual review, but does not claim that the question itself was answered.
    safe = result.get("answer_type") in {"out_of_scope", "not_found", "clarify", "extracted"}
    return {"id": case["id"], "category": case["category"], "question": case["question"],
            "passed": safe, "manual_review": result.get("answer_type") == "extracted", "result": result}


def multi_turn(case: dict) -> dict:
    history = []
    turns = []
    for question in case["turns"]:
        try:
            result = answer(question, history)
        except Exception as exc:
            return {"id": case["id"], "turns": case["turns"], "passed": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)}, "results": turns}
        turns.append(result)
        history.append(result)
    final = turns[-1]
    haystack = source_text(final).lower()
    passed = (final.get("answer_type") in {"generated", "extracted"} and cited(final)
              and (final.get("answer_type") == "extracted" or not final.get("unsupported_commands"))
              and any(term.lower() in haystack for term in case["expect_any"]))
    return {"id": case["id"], "turns": case["turns"], "passed": passed, "results": turns}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--only", choices=("answerable", "unanswerable", "multi_turn"))
    args = parser.parse_args()
    runtime = health()
    if not runtime.get("rag_ready"):
        raise SystemExit("真实模型/RAG 未就绪：" + "；".join(runtime.get("errors", [])))
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    started = time.perf_counter()
    rows = {"answerable": [], "unanswerable": [], "multi_turn": []}
    RESULTS.mkdir(exist_ok=True)
    output = RESULTS / f"p0-quality-{args.tag}.json"
    evaluators = (("answerable", answerable), ("unanswerable", unanswerable), ("multi_turn", multi_turn))
    for key, evaluator in evaluators:
        if args.only and key != args.only:
            continue
        for case in cases[key]:
            before = time.perf_counter()
            row = evaluator(case)
            row["wall_s"] = round(time.perf_counter() - before, 3)
            rows[key].append(row)
            print(f"{key:12} {case['id']} {'PASS' if row['passed'] else 'FAIL'} {row['wall_s']:.3f}s", flush=True)
            output.write_text(json.dumps({"state": "running", "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    request_latencies = [row["result"]["latency_s"] for key in ("answerable", "unanswerable")
                         for row in rows[key] if row.get("result")]
    request_latencies += [turn["latency_s"] for row in rows["multi_turn"] for turn in row["results"]]
    case_wall = [row["wall_s"] for group in rows.values() for row in group]
    summary = {
        "answerable": {"passed": sum(row["passed"] for row in rows["answerable"]), "total": len(rows["answerable"])},
        "unanswerable": {"passed": sum(row["passed"] for row in rows["unanswerable"]), "total": len(rows["unanswerable"]),
                         "manual_review": sum(row["manual_review"] for row in rows["unanswerable"])},
        "multi_turn": {"passed": sum(row["passed"] for row in rows["multi_turn"]), "total": len(rows["multi_turn"])},
        "request_latency_p50_s": round(statistics.median(request_latencies), 3) if request_latencies else None,
        "request_latency_max_s": round(max(request_latencies), 3) if request_latencies else None,
        "case_wall_max_s": round(max(case_wall), 3),
        "wall_total_s": round(time.perf_counter() - started, 3),
        "runtime": {key: runtime.get(key) for key in ("backend", "model_name", "index_revision", "retrieval_mode", "chunks", "vectors")},
    }
    summary["performance_gate_30s"] = bool(summary["request_latency_max_s"] is not None
                                           and summary["request_latency_max_s"] <= 30)
    output.write_text(json.dumps({"state": "complete", "summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(output)
    if args.only:
        group = summary[args.only]
        required = (9 * group["total"] + 9) // 10 if args.only == "answerable" else group["total"]
        passed = group["passed"] >= required and summary["performance_gate_30s"]
    else:
        passed = (summary["answerable"]["passed"] >= 9 and summary["unanswerable"]["passed"] == 12
                  and summary["multi_turn"]["passed"] == 5 and summary["performance_gate_30s"])
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
