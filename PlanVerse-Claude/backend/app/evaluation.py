"""Ground-truth evaluation: baseline (parser + basic post-processing) vs PlanVerse
(same parser + TopologyGuard + ScaleLock).

Annotation format (coordinates in ORIGINAL image pixels):
{
  "meters_per_px": 0.02,                       # optional, needed for scale / dimension error
  "rooms":   [{"polygon": [[x, y], ...], "type": "bedroom"}],
  "doors":   [{"x1": .., "y1": .., "x2": .., "y2": ..}],
  "windows": [{"x1": .., "y1": .., "x2": .., "y2": ..}]
}
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from shapely.geometry import Polygon

from .pipeline import scalelock as sl

IOU_MATCH = 0.5


def _poly(pts) -> Polygon:
    p = Polygon(pts)
    return p if p.is_valid else p.buffer(0)


def _rect_dims(pts) -> tuple[float, float]:
    (_, _), (w, h), _ = cv2.minAreaRect(np.array(pts, np.float32))
    return max(w, h), min(w, h)


def _match_rooms(pred: list[dict], gt: list[dict]) -> list[tuple[int, int, float]]:
    pairs = []
    pp = [_poly(r["polygon"]) for r in pred]
    gp = [_poly(r["polygon"]) for r in gt]
    for i, p in enumerate(pp):
        for j, g in enumerate(gp):
            inter = p.intersection(g).area
            if inter <= 0:
                continue
            iou = inter / p.union(g).area
            if iou >= IOU_MATCH:
                pairs.append((iou, i, j))
    pairs.sort(reverse=True)
    used_p, used_g, out = set(), set(), []
    for iou, i, j in pairs:
        if i in used_p or j in used_g:
            continue
        used_p.add(i); used_g.add(j)
        out.append((i, j, iou))
    return out


def _f1_openings(pred: list[dict], gt: list[dict]) -> dict:
    cands = []
    for i, p in enumerate(pred):
        pc = ((p["x1"] + p["x2"]) / 2, (p["y1"] + p["y2"]) / 2)
        for j, g in enumerate(gt):
            gc = ((g["x1"] + g["x2"]) / 2, (g["y1"] + g["y2"]) / 2)
            gw = math.hypot(g["x2"] - g["x1"], g["y2"] - g["y1"])
            d = math.hypot(pc[0] - gc[0], pc[1] - gc[1])
            if d <= 0.5 * gw + 4:
                cands.append((d, i, j))
    cands.sort()
    up, ug = set(), set()
    for d, i, j in cands:
        if i in up or j in ug:
            continue
        up.add(i); ug.add(j)
    tp = len(up)
    prec = tp / len(pred) if pred else (1.0 if not gt else 0.0)
    rec = tp / len(gt) if gt else (1.0 if not pred else 0.0)
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "predicted": len(pred), "actual": len(gt), "precision": round(prec, 4),
            "recall": round(rec, 4), "f1": round(f1, 4)}


def _scale_gt(gt: dict, f: float) -> dict:
    """Convert annotation from original-image pixels to working-image pixels."""
    def sc(o):
        return {**o, "x1": o["x1"] * f, "y1": o["y1"] * f, "x2": o["x2"] * f, "y2": o["y2"] * f}
    out = {
        "rooms": [{**r, "polygon": [[x * f, y * f] for x, y in r["polygon"]]} for r in gt.get("rooms", [])],
        "doors": [sc(o) for o in gt.get("doors", [])],
        "windows": [sc(o) for o in gt.get("windows", [])],
    }
    if gt.get("meters_per_px"):
        out["meters_per_px"] = float(gt["meters_per_px"]) / f
    return out


def evaluate_version(rooms: list[dict], openings: list[dict], stats: dict, scale: float, gt: dict) -> dict:
    matches = _match_rooms(rooms, gt["rooms"])
    n_gt = len(gt["rooms"])
    res = {
        "room_recall": round(len(matches) / n_gt, 4) if n_gt else None,
        "room_precision": round(len(matches) / len(rooms), 4) if rooms else 0.0,
        "room_iou_matched": round(float(np.mean([m[2] for m in matches])), 4) if matches else 0.0,
        "room_iou_all": round(float(sum(m[2] for m in matches) / n_gt), 4) if n_gt else None,
        "rooms_predicted": len(rooms), "rooms_actual": n_gt,
        "structural_consistency": stats["connected_endpoint_ratio"],
    }
    typed = [(rooms[i], gt["rooms"][j]) for i, j, _ in matches if gt["rooms"][j].get("type")]
    res["room_type_accuracy"] = round(sum(1 for p, g in typed if p["type"] == g["type"]) / len(typed), 4) if typed else None
    res["doors"] = _f1_openings([o for o in openings if o["type"] == "door"], gt["doors"])
    res["windows"] = _f1_openings([o for o in openings if o["type"] == "window"], gt["windows"])
    s_gt = gt.get("meters_per_px")
    if s_gt:
        res["scale_error_pct"] = round(abs(scale - s_gt) / s_gt * 100, 3)
        errs = []
        for i, j, _ in matches:
            pl, pw = _rect_dims(rooms[i]["polygon"])
            gl, gw = _rect_dims(gt["rooms"][j]["polygon"])
            errs += [abs(pl * scale - gl * s_gt) / (gl * s_gt), abs(pw * scale - gw * s_gt) / (gw * s_gt)]
        res["dimension_error_pct"] = round(float(np.mean(errs)) * 100, 3) if errs else None
    return res


def evaluate_session(sess, gt_raw: dict) -> dict:
    if getattr(sess, "edited", False):
        raise ValueError("this plan contains manually edited geometry, which is excluded from automatic scores")
    gt = _scale_gt(gt_raw, sess.image.resample)
    est = sl.estimate_fallback(sess.original.openings, sess.thickness)["scale"]
    # The baseline has no ScaleLock, so it uses the same estimated scale fallback.
    base = evaluate_version(sess.original.rooms, sess.original.openings, sess.original.stats(), est, gt)
    pv_scale = sess.auto_scale["scale"] or sl.estimate_fallback(sess.corrected.openings, sess.thickness)["scale"]
    pv = evaluate_version(sess.corrected.rooms, sess.corrected.openings, sess.corrected.stats(), pv_scale, gt)
    return {"parser": "OpenCV structural parser (same parser for both)", "baseline": base, "planverse": pv,
            "scale_status": "auto" if sess.auto_scale["scale"] else "estimated",
            "note": "Manual calibration and edits are excluded from automatic scores."}
