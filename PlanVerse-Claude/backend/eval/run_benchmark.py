"""Controlled comparison on generated plans with exact ground truth.

Baseline : OpenCV structural parser + basic post-processing (estimated scale).
PlanVerse: the same parser + TopologyGuard + ScaleLock.

Usage:  python -m eval.run_benchmark [count]
Writes eval/results/benchmark.json and eval/results/benchmark.md
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from app.evaluation import evaluate_session
from app.pipeline.run import process_plan

from .synth import generate

OUT = Path(__file__).resolve().parent / "results"
SCALARS = ["room_recall", "room_precision", "room_iou_matched", "room_iou_all", "room_type_accuracy",
           "dimension_error_pct", "scale_error_pct", "structural_consistency"]


def _micro(rows: list[dict], key: str) -> dict:
    tp = sum(r[key]["tp"] for r in rows)
    pred = sum(r[key]["predicted"] for r in rows)
    act = sum(r[key]["actual"] for r in rows)
    p = tp / pred if pred else 0.0
    rc = tp / act if act else 0.0
    return {"tp": tp, "predicted": pred, "actual": act, "precision": round(p, 4), "recall": round(rc, 4),
            "f1": round(2 * p * rc / (p + rc), 4) if p + rc else 0.0}


def aggregate(rows: list[dict]) -> dict:
    out = {}
    for k in SCALARS:
        vals = [r[k] for r in rows if r.get(k) is not None]
        out[k] = round(statistics.mean(vals), 4) if vals else None
    out["doors"] = _micro(rows, "doors")
    out["windows"] = _micro(rows, "windows")
    return out


def main(count: int = 20, first_seed: int = 100) -> dict:
    per_plan = []
    base_rows, pv_rows = [], []
    t0 = time.time()
    for seed in range(first_seed, first_seed + count):
        png, gt = generate(seed)
        sess = process_plan(png, f"generated_{seed}.png")
        res = evaluate_session(sess, gt)
        base_rows.append(res["baseline"])
        pv_rows.append(res["planverse"])
        per_plan.append({"seed": seed, "units": gt["units"], "rooms": len(gt["rooms"]), "defects": len(gt["defects"]),
                         "scale_status": res["scale_status"],
                         "baseline_room_recall": res["baseline"]["room_recall"],
                         "planverse_room_recall": res["planverse"]["room_recall"],
                         "planverse_scale_error_pct": res["planverse"].get("scale_error_pct")})
        print(f"seed {seed}: rooms {len(gt['rooms'])}, recall {res['baseline']['room_recall']:.2f} -> "
              f"{res['planverse']['room_recall']:.2f}, scale {res['scale_status']}")
    result = {
        "count": count,
        "parser": "OpenCV structural parser (identical in both columns)",
        "baseline": aggregate(base_rows),
        "planverse": aggregate(pv_rows),
        "auto_calibrated": sum(1 for p in per_plan if p["scale_status"] == "auto"),
        "per_plan": per_plan,
        "seconds": round(time.time() - t0, 1),
        "note": ("Generated plans are drawn in one conventional style with injected wall breaks and junction gaps; "
                 "results on real-world plans will differ. Baseline uses an estimated scale because it has no ScaleLock."),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "benchmark.json").write_text(json.dumps(result, indent=1))
    lines = [f"# Benchmark: {count} generated plans (seeds {first_seed}-{first_seed + count - 1})", "",
             "Same OpenCV parser in both columns. PlanVerse adds TopologyGuard + ScaleLock.", "",
             "| Metric | Baseline | PlanVerse |", "|---|---|---|"]
    for k in SCALARS:
        lines.append(f"| {k} | {result['baseline'][k]} | {result['planverse'][k]} |")
    for k in ("doors", "windows"):
        lines.append(f"| {k} F1 (micro) | {result['baseline'][k]['f1']} | {result['planverse'][k]['f1']} |")
    lines += ["", f"Automatically calibrated: {result['auto_calibrated']}/{count}", "", result["note"]]
    (OUT / "benchmark.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
