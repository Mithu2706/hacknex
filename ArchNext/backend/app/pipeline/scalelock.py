"""ScaleLock: real-world calibration from dimension text, with manual and estimated fallbacks."""
from __future__ import annotations

import math
import statistics

import cv2
import numpy as np

from .measure import parse_dimension
from .ocr import TextItem

AGREE_TOL = 0.08          # measurements agree when their scales differ by less than 8 %
PAIR_SELF_TOL = 0.12      # both sides of a room label must imply the same scale within 12 %
TYPICAL_DOOR_M = 0.85     # used only for the clearly-labelled estimated fallback
TYPICAL_WALL_M = 0.15
DEFAULT_WALL_HEIGHT_M = 2.7
DEFAULT_DOOR_HEIGHT_M = 2.1
DEFAULT_SILL_M = 0.9
DEFAULT_HEAD_M = 2.1


def _room_at(room_labels: np.ndarray, x: float, y: float) -> int:
    H, W = room_labels.shape
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < W and 0 <= yi < H:
        return int(room_labels[yi, xi])
    return 0


def find_dimension_line(item: TextItem, dark: np.ndarray, wall_mask: np.ndarray) -> tuple[float, list[float]] | None:
    """Locate the dimension line that a stand-alone measurement annotates.

    Returns (length_px, [x1, y1, x2, y2]) or None.
    """
    thin = cv2.bitwise_and(dark, cv2.bitwise_not(cv2.dilate(wall_mask, np.ones((5, 5), np.uint8))))
    img = thin.T if item.vertical else thin
    if item.vertical:
        tx0, tx1, ty0, ty1 = item.y, item.y + item.h, item.x, item.x + item.w
    else:
        tx0, tx1, ty0, ty1 = item.x, item.x + item.w, item.y, item.y + item.h
    th = ty1 - ty0
    tw = tx1 - tx0
    H, W = img.shape
    best = None
    for r in range(int(max(1, ty0 - 1.5 * th)), int(min(H - 1, ty1 + 1.5 * th))):
        prof = img[r - 1:r + 2].any(axis=0)
        prof[int(max(0, tx0 - 3)):int(min(W, tx1 + 3))] = True
        c = int(min(W - 1, max(0, (tx0 + tx1) / 2)))
        left = c
        gap = 0
        while left > 0 and gap <= 2:
            left -= 1
            gap = 0 if prof[left] else gap + 1
        left += gap
        right = c
        gap = 0
        while right < W - 1 and gap <= 2:
            right += 1
            gap = 0 if prof[right] else gap + 1
        right -= gap
        ext_l, ext_r = tx0 - left, right - tx1
        if ext_l < 0.5 * th or ext_r < 0.5 * th:
            continue
        length = right - left
        if length < 1.5 * tw:
            continue
        if best is None or length > best[0]:
            best = (length, left, right, r)
    if best is None:
        return None
    length, left, right, r = best
    seg = [left, r, right, r] if not item.vertical else [r, left, r, right]
    return float(length), [float(v) for v in seg]


def collect_measurements(texts: list[TextItem], rooms: list[dict], room_labels: np.ndarray,
                         dark: np.ndarray, wall_mask: np.ndarray) -> list[dict]:
    out = []
    # A detected space holding several room-size labels is several rooms merged together; none of
    # those labels describes the space, and they would falsely "agree" with each other.
    labels_per_room: dict[int, int] = {}
    for it in texts:
        dim = parse_dimension(it.text)
        if dim and dim["kind"] == "pair":
            rid = _room_at(room_labels, it.cx, it.cy)
            labels_per_room[rid] = labels_per_room.get(rid, 0) + 1
    for it in texts:
        dim = parse_dimension(it.text)
        if not dim:
            continue
        m = {"text": it.text, "kind": dim["kind"], "bbox": [round(it.x, 1), round(it.y, 1), round(it.w, 1), round(it.h, 1)],
             "candidates": [], "status": "rejected", "reason": "", "room": None, "line": None, "px": None}
        if dim["kind"] == "pair":
            rid = _room_at(room_labels, it.cx, it.cy)
            if rid == 0:
                m["reason"] = "Not inside a detected room"
                out.append(m)
                continue
            room = rooms[rid - 1]
            m["room"] = room["id"]
            if labels_per_room.get(rid, 0) > 1:
                m["reason"] = "Several room labels fall inside one detected space (rooms are probably merged)"
                out.append(m)
                continue
            if room["rectangularity"] < 0.82:
                m["reason"] = "Room shape is not rectangular enough to compare with its label"
                out.append(m)
                continue
            long_px, short_px = room["rect_px"]
            m["px"] = [long_px, short_px]
            a, b = dim["lengths"]
            for (ua, ma) in a.candidates("room"):
                for (ub, mb) in b.candidates("room"):
                    if ua != ub:
                        continue
                    L, S = max(ma, mb), min(ma, mb)
                    s1, s2 = L / long_px, S / short_px
                    if abs(s1 - s2) / ((s1 + s2) / 2) <= PAIR_SELF_TOL:
                        m["candidates"].append({"unit": ua, "inferred": a.unit is None, "scale": (s1 + s2) / 2,
                                                "meters": [round(L, 3), round(S, 3)]})
            if not m["candidates"]:
                m["reason"] = ("Label proportions do not match the detected room shape"
                               if a.candidates("room") and b.candidates("room") else "Not a plausible room size")
        else:
            found = find_dimension_line(it, dark, wall_mask)
            if not found:
                m["reason"] = "No dimension line found next to the value"
                out.append(m)
                continue
            length_px, seg = found
            m["line"] = seg
            m["px"] = [round(length_px, 1)]
            for (u, meters) in dim["lengths"][0].candidates("line"):
                m["candidates"].append({"unit": u, "inferred": dim["lengths"][0].unit is None,
                                        "scale": meters / length_px, "meters": [round(meters, 3)]})
            if not m["candidates"]:
                m["reason"] = "Not a plausible building dimension"
        out.append(m)
    return out


def _weight(m: dict, cand: dict) -> float:
    explicit = not cand.get("inferred", False)
    base = 1.0 if m["kind"] == "pair" else 0.6
    return base * (1.0 if explicit else 0.85)


def consensus(measurements: list[dict], extent_px: float) -> dict:
    cands = []
    for mi, m in enumerate(measurements):
        for c in m["candidates"]:
            meters_extent = extent_px * c["scale"]
            if not (3.0 <= meters_extent <= 300.0):
                continue
            cands.append((mi, c, _weight(m, c)))
    if not cands:
        for m in measurements:
            if m["candidates"] and not m["reason"]:
                m["reason"] = "Implies an implausible building size"
        return {"scale": None, "accepted": [], "confidence": None}
    best = None
    for (mi, c, w) in cands:
        support: dict[int, float] = {}
        for (mj, cj, wj) in cands:
            if abs(math.log(cj["scale"] / c["scale"])) <= math.log(1 + AGREE_TOL):
                support[mj] = max(support.get(mj, 0.0), wj)
        score = (len(support), sum(support.values()))
        if best is None or score > best[0]:
            best = (score, c["scale"])
    centre = best[1]
    # Refine around the median of supporting candidates, then select one interpretation per measurement.
    for _ in range(2):
        chosen = {}
        for (mi, c, w) in cands:
            d = abs(math.log(c["scale"] / centre))
            if d <= math.log(1 + AGREE_TOL) and (mi not in chosen or d < chosen[mi][1]):
                chosen[mi] = (c, d)
        centre = statistics.median(c["scale"] for c, _ in chosen.values())
    accepted = sorted(chosen)
    for mi, m in enumerate(measurements):
        if mi in chosen:
            m["status"] = "accepted"
            m["reason"] = ""
            m["chosen"] = chosen[mi][0]
        elif m["candidates"]:
            m["status"] = "rejected"
            m["reason"] = "Inconsistent with the other measurements" if len(accepted) > 1 else (m["reason"] or "Could not be confirmed by another measurement")
    n = len(accepted)
    if n >= 3:
        conf = "high"
    elif n == 2:
        conf = "medium"
    elif n == 1 and measurements[accepted[0]]["kind"] == "pair":
        conf = "low"
    else:
        for mi in accepted:
            measurements[mi]["status"] = "rejected"
            measurements[mi]["reason"] = "A single unconfirmed value is not reliable enough"
        return {"scale": None, "accepted": [], "confidence": None}
    return {"scale": centre, "accepted": accepted, "confidence": conf}


def leave_one_out(measurements: list[dict], accepted: list[int]) -> list[dict]:
    """Hold-out check: predict each accepted measurement from the scale of the others."""
    rows = []
    if len(accepted) < 2:
        return rows
    for mi in accepted:
        others = [measurements[j]["chosen"]["scale"] for j in accepted if j != mi]
        s = statistics.median(others)
        m = measurements[mi]
        labelled = m["chosen"]["meters"]
        px = sorted(m["px"], reverse=True)
        for lab, p in zip(labelled, px):
            pred = p * s
            rows.append({"text": m["text"], "labelled_m": round(lab, 3), "predicted_m": round(pred, 3),
                         "error_pct": round(abs(pred - lab) / lab * 100, 2)})
    return rows


def estimate_fallback(openings: list[dict], thickness_px: float) -> dict:
    doors = [o["width"] for o in openings if o["type"] == "door" and o["confidence"] in ("high", "medium")]
    if len(doors) >= 2:
        s = TYPICAL_DOOR_M / statistics.median(doors)
        return {"scale": s, "basis": f"typical door width ({TYPICAL_DOOR_M:.2f} m) applied to {len(doors)} detected doors"}
    return {"scale": TYPICAL_WALL_M / max(thickness_px, 1.0),
            "basis": f"typical wall thickness ({TYPICAL_WALL_M:.2f} m) applied to the detected walls"}


def manual_scale(p1: list[float], p2: list[float], meters: float) -> float:
    d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if d < 5:
        raise ValueError("The two calibration points are too close together.")
    if not (0.05 <= meters <= 1000):
        raise ValueError("Enter a real-world distance between 0.05 m and 1000 m.")
    return meters / d
