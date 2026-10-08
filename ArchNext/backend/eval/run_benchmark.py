"""Four-way ablation on generated plans with exact ground truth.

Every configuration runs the full pipeline independently on the same images with the same parser:
  1. Baseline            - TopologyGuard OFF, ScaleLock OFF (estimated scale)
  2. TopologyGuard only  - TopologyGuard ON,  ScaleLock OFF (estimated scale)
  3. ScaleLock only      - TopologyGuard OFF, ScaleLock ON
  4. Full ArchNext       - TopologyGuard ON,  ScaleLock ON

Usage:  python -m eval.run_benchmark [count] [--verify]
Writes eval/results/benchmark.json and eval/results/benchmark.md
--verify runs the whole study a second time and checks the metrics are identical.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path

from app.evaluation import CONFIGS, PARSER_NOTE, _scale_gt, evaluate_config_session
from app.pipeline.run import PARSER_ID, process_plan

from .synth import generate

OUT = Path(__file__).resolve().parent / "results"
SCALARS = ["room_recall", "room_precision", "room_iou_matched", "room_iou_all", "room_type_accuracy",
           "dimension_error_pct", "scale_error_pct", "structural_consistency"]
LABEL = "Synthetic benchmark — {n} generated floor plans. Results do not establish real-world accuracy."
DEFINITIONS = {
    "room_recall": "Share of true rooms matched by a detected room with IoU >= 0.5.",
    "room_precision": "Share of detected rooms that match a true room (IoU >= 0.5).",
    "room_iou_all": "Mean overlap (intersection over union) per true room; unmatched rooms count as 0.",
    "room_iou_matched": "Mean overlap of matched rooms only.",
    "room_type_accuracy": "Share of matched rooms whose type (bedroom, kitchen, ...) is correct.",
    "dimension_error_pct": "Mean relative error of matched room length and width in metres.",
    "scale_error_pct": "Relative error of the metres-per-pixel scale.",
    "structural_consistency": "Share of wall ends connected to another wall or an opening.",
    "doors_f1": "Door detection F1 (micro-averaged over all plans), centre within half a door width.",
    "windows_f1": "Window detection F1 (micro-averaged over all plans).",
}


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
        out[f"{k}_n"] = len(vals)
    out["doors"] = _micro(rows, "doors")
    out["windows"] = _micro(rows, "windows")
    out["auto_scaled_plans"] = sum(1 for r in rows if r.get("scale_method") == "automatic")
    return out


def run_study(count: int, first_seed: int) -> dict:
    rows = {c["key"]: [] for c in CONFIGS}
    per_plan = []
    for seed in range(first_seed, first_seed + count):
        png, gt = generate(seed)
        entry = {"seed": seed, "units": gt["units"], "rooms": len(gt["rooms"]), "defects": len(gt["defects"])}
        for c in CONFIGS:
            sess = process_plan(png, f"generated_{seed}.png", topology_guard=c["topology_guard"],
                                scale_lock=c["scale_lock"])
            res = evaluate_config_session(sess, _scale_gt(gt, sess.image.resample))
            rows[c["key"]].append(res)
            entry[c["key"]] = {k: res.get(k) for k in ("room_recall", "room_iou_all", "dimension_error_pct",
                                                        "scale_error_pct", "structural_consistency", "scale_method")}
        per_plan.append(entry)
        print(f"seed {seed}: room recall " + "  ".join(f"{c['key']}={entry[c['key']]['room_recall']:.2f}" for c in CONFIGS))
    return {"results": {k: aggregate(v) for k, v in rows.items()}, "per_plan": per_plan}


def main(count: int = 20, first_seed: int = 100, verify: bool = False) -> dict:
    t0 = time.time()
    study = run_study(count, first_seed)
    reproducible = None
    if verify:
        again = run_study(count, first_seed)
        reproducible = again["results"] == study["results"]
    result = {
        "dataset": {"kind": "synthetic", "label": LABEL.format(n=count), "count": count,
                    "seeds": [first_seed, first_seed + count - 1], "generator": "eval/synth.py",
                    "description": "Generated plans in one drafting style with injected wall breaks, junction gaps "
                                   "and speckle noise; exact ground truth for rooms, doors, windows and scale."},
        "parser": PARSER_NOTE, "parser_id": PARSER_ID,
        "configs": [{k: c[k] for k in ("key", "label", "topology_guard", "scale_lock")} for c in CONFIGS],
        **study,
        "definitions": DEFINITIONS,
        "notes": {"scale": "Configurations without ScaleLock use the estimated scale (typical door width), so "
                           "their scale and dimension errors measure that fallback."},
        "reproducibility": {"verified": verify, "identical": reproducible},
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "benchmark.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    lines = [f"# {result['dataset']['label']}", "",
             f"Seeds {first_seed}-{first_seed + count - 1}. {PARSER_NOTE}.", "",
             "| Metric | " + " | ".join(c["label"] for c in CONFIGS) + " |",
             "|---|" + "---|" * len(CONFIGS)]
    for k in SCALARS:
        lines.append(f"| {k} | " + " | ".join(str(result["results"][c["key"]][k]) for c in CONFIGS) + " |")
    for k in ("doors", "windows"):
        lines.append(f"| {k} F1 (micro) | " + " | ".join(str(result["results"][c["key"]][k]["f1"]) for c in CONFIGS) + " |")
    lines += ["", f"Reproducibility check: {'identical on re-run' if reproducible else 'not run' if reproducible is None else 'DIFFERENT on re-run'}",
              "", result["notes"]["scale"]]
    (OUT / "benchmark.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(int(args[0]) if args else 20, verify="--verify" in sys.argv)
