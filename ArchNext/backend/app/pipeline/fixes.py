"""Issue-based geometry corrections (first part of Fix2Build).

After the automatic TopologyGuard pass, the remaining structural problems are re-detected on the
CURRENT geometry. Each issue either carries a safe, previewable fix or is marked as requiring
manual review. Fixes are only offered when:
  * the change is local and bounded by the wall thickness,
  * the gap shows no door-swing or glazing evidence (doors are never closed),
  * the new geometry does not cover an existing door or window,
  * the targeted wall end is actually connected afterwards.
"""
from __future__ import annotations

import cv2
import numpy as np
from shapely.geometry import LineString

from .structure import (CONNECT_TOL, MIN_OPENING, classify_gap, end_connected, endpoints, find_gaps,
                        opening_polygon, unit, wall_polygon)
from .topology import Issue, _axis_extent, _merge_axis, endpoint_report, opening_context_issues
from .walls import Wall

FIX_LABEL = {
    "close_gap": "Close gap",
    "connect": "Connect walls",
    "align_corner": "Align junction",
    "merge_duplicate": "Remove duplicate",
}


def _key(check: str, ids: list[str], x: float, y: float) -> str:
    return f"{check}:{'-'.join(sorted(ids))}:{int(round(x / 3))},{int(round(y / 3))}"


def _extend(w: Wall, end: int, d: float) -> None:
    ux, uy = unit(w)
    if end == 0:
        w.x1 -= ux * d
        w.y1 -= uy * d
    else:
        w.x2 += ux * d
        w.y2 += uy * d


def apply_fix(walls: list[Wall], spec: dict) -> list[Wall]:
    """Return a new wall list with the fix applied (inputs are not modified)."""
    ws = [w.copy() for w in walls]
    idx = {w.id: i for i, w in enumerate(ws)}
    kind = spec["kind"]
    if kind == "connect":
        w = ws[idx[spec["a"]]]
        _extend(w, spec["end"], spec["dist"])
        w.source = "edited"
    elif kind in ("close_gap", "merge_duplicate"):
        a, b = ws[idx[spec["a"]]], ws[idx[spec["b"]]]
        m = _merge_axis([a, b])
        m.id = a.id
        m.exterior = a.exterior or b.exterior
        m.source = "edited"
        ws[idx[spec["a"]]] = m
        ws = [w for w in ws if w.id != spec["b"]]
    elif kind == "align_corner":
        for wid, end, x, y in spec["moves"]:
            w = ws[idx[wid]]
            if end == 0:
                w.x1, w.y1 = x, y
            else:
                w.x2, w.y2 = x, y
            w.source = "edited"
    else:
        raise ValueError(f"unknown fix kind {kind}")
    return ws


def _end_index(w: Wall, x: float, y: float) -> int:
    return 0 if np.hypot(w.x1 - x, w.y1 - y) <= np.hypot(w.x2 - x, w.y2 - y) else 1


def _validate(walls: list[Wall], new: list[Wall], spec: dict, openings: list[dict],
              targets: list[tuple[str, int]]) -> str | None:
    """Return a reason the fix is unsafe, or None when it is safe."""
    changed = {w.id for w in new if w.source == "edited"} & set(spec.get("ids", []))
    new_by_id = {w.id: w for w in new}
    old_by_id = {w.id: w for w in walls}
    for wid in changed:
        p = wall_polygon(new_by_id[wid])
        added = p.difference(wall_polygon(old_by_id[wid])) if wid in old_by_id else p
        for o in openings:
            op = opening_polygon(o)
            if added.intersection(op).area > 0.15 * op.area:
                return f"the change would cover a detected {o['type']}"
    polys = [wall_polygon(w) for w in new]
    idx = {w.id: i for i, w in enumerate(new)}
    for wid, end in targets:
        if wid not in idx:
            continue
        if not end_connected(new, polys, idx[wid], end, tol=CONNECT_TOL):
            return "the wall end would still not be connected"
    return None


def _misaligned_corner(walls: list[Wall], i: int, end: int, t: float) -> dict | None:
    a = walls[i]
    if a.orient not in "hv":
        return None
    px, py, dx, dy = endpoints(a)[end]
    best = None
    for j, b in enumerate(walls):
        if j == i or b.orient not in "hv" or b.orient == a.orient:
            continue
        for bend in (0, 1):
            qx, qy, bdx, bdy = endpoints(b)[bend]
            d = np.hypot(px - qx, py - qy)
            if d > 2.0 * t or (best and d >= best[0]):
                continue
            # Corner target: A reaches the outer face of B, B reaches the outer face of A.
            if a.orient == "h":
                ac = (a.y1 + a.y2) / 2
                bc = (b.x1 + b.x2) / 2
                new_a = (bc + np.sign(dx) * b.thickness / 2, ac)
                new_b = (bc, ac + np.sign(bdy) * a.thickness / 2)
            else:
                ac = (a.x1 + a.x2) / 2
                bc = (b.y1 + b.y2) / 2
                new_a = (ac, bc + np.sign(dy) * b.thickness / 2)
                new_b = (ac + np.sign(bdx) * a.thickness / 2, bc)
            move_a = np.hypot(new_a[0] - px, new_a[1] - py)
            move_b = np.hypot(new_b[0] - qx, new_b[1] - qy)
            if max(move_a, move_b) > 2.0 * t or max(move_a, move_b) < 0.5:
                continue
            # Neither wall may flip direction or shrink to nothing.
            if move_a > 0.6 * a.length or move_b > 0.6 * b.length:
                continue
            best = (d, {"kind": "align_corner", "ids": [a.id, b.id],
                        "moves": [[a.id, end, float(new_a[0]), float(new_a[1])],
                                  [b.id, bend, float(new_b[0]), float(new_b[1])]]})
    return best[1] if best else None


def _context(x: float, y: float, labels: np.ndarray, exterior: np.ndarray, rooms: list[dict], t: float) -> str:
    H, W = labels.shape
    r = int(max(3, 1.5 * t))
    x0, x1 = int(max(0, x - r)), int(min(W, x + r + 1))
    y0, y1 = int(max(0, y - r)), int(min(H, y + r + 1))
    ids = set(np.unique(labels[y0:y1, x0:x1]).tolist()) - {0}
    out = bool(exterior[y0:y1, x0:x1].any())
    names = [rooms[k - 1]["name"] or f"Room {k}" for k in sorted(ids) if k - 1 < len(rooms)]
    if out and names:
        return f"{', '.join(names)} leaks to the outside here."
    if out:
        return "The building outline may be open here."
    return ""


def detect_review_issues(walls: list[Wall], openings: list[dict], t: float, ink: np.ndarray,
                         labels: np.ndarray, exterior: np.ndarray, rooms: list[dict]) -> tuple[list[Issue], dict]:
    """Detect remaining structural issues on the current geometry.

    Returns (issues, specs) where specs maps an issue key to its internal fix specification.
    """
    issues: list[Issue] = []
    specs: dict[str, dict] = {}
    ink_dil = cv2.dilate(ink, np.ones((5, 5), np.uint8))
    covered: set[tuple[str, int]] = set()

    def add(issue: Issue, spec: dict | None, targets: list[tuple[str, int]]):
        key = _key(issue.check, issue.walls, issue.at[0], issue.at[1])
        if spec is not None:
            new = apply_fix(walls, spec)
            reason = _validate(walls, new, spec, openings, targets)
            if reason:
                issue.message += f" Manual review required: {reason}."
                spec = None
            else:
                ids = set(spec["ids"])
                after = {w.id: w for w in new}
                issue.fix = {
                    "kind": spec["kind"], "label": FIX_LABEL[spec["kind"]],
                    "before": [w.to_dict() for w in walls if w.id in ids],
                    "after": [after[i].to_dict() for i in spec["ids"] if i in after],
                    "removed": [i for i in spec["ids"] if i not in after],
                }
                specs[key] = spec
        issue.key = key
        issues.append(issue)

    # 1. Remaining small gaps (narrower than any opening) and short junctions.
    for g in find_gaps(walls, t, max_mult=MIN_OPENING, corners=False):
        a, b = walls[g.a], walls[g.b]
        mid = [(g.sx + g.hx) / 2, (g.sy + g.hy) / 2]
        covered.add((a.id, g.end))
        if g.kind == "collinear":
            covered.add((b.id, _end_index(b, g.hx, g.hy)))
        if g.kind == "oblique":
            add(Issue("intersections", "review", "A wall meets another wall at an unusual angle. Manual review required.",
                      mid, [a.id, b.id]), None, [])
            continue
        cls = ink_cls = classify_gap(g, walls, ink, ink_dil)
        evidence = ink_cls["type"] in ("door", "window") and ink_cls["confidence"] != "low"
        if g.kind == "collinear":
            msg = f"A {g.dist:.0f}px gap in a straight wall is too narrow to be a door or window."
            if evidence:
                add(Issue("ambiguous_gaps", "review",
                          f"A narrow gap shows {cls['type']} markings, so it is left open. Manual review required.",
                          mid, [a.id, b.id]), None, [])
                continue
            ratio = max(a.thickness, b.thickness) / max(min(a.thickness, b.thickness), 1e-6)
            if a.orient in "hv" and a.orient == b.orient and ratio <= 1.6:
                spec = {"kind": "close_gap", "ids": [a.id, b.id], "a": a.id, "b": b.id}
            else:
                spec = {"kind": "connect", "ids": [a.id], "a": a.id, "end": g.end, "dist": g.dist + 0.5}
            add(Issue("ambiguous_gaps", "review", msg, mid, [a.id, b.id]), spec, [(a.id, g.end)] if spec["kind"] == "connect" else [])
        else:
            msg = f"A wall stops {g.dist:.0f}px short of the wall it appears to meet."
            if evidence:
                add(Issue("junction_gaps", "review",
                          f"A wall stops short of a junction, but the gap shows {cls['type']} markings. Manual review required.",
                          mid, [a.id, b.id]), None, [])
                continue
            spec = {"kind": "connect", "ids": [a.id], "a": a.id, "end": g.end, "dist": g.dist + b.thickness / 2}
            add(Issue("junction_gaps", "review", msg, mid, [a.id, b.id]), spec, [(a.id, g.end)])

    # 2. Remaining disconnected wall ends.
    dangling, _, _ = endpoint_report(walls, t, openings)
    for (i, end, x, y) in dangling:
        w = walls[i]
        if (w.id, end) in covered:
            continue
        ctx = _context(x, y, labels, exterior, rooms, t)
        spec = _misaligned_corner(walls, i, end, t)
        if spec:
            other = spec["ids"][1]
            oend = spec["moves"][1][1]
            covered.add((other, oend))
            add(Issue("dangling", "review", ("Two walls almost meet at a corner but are misaligned. " + ctx).strip(),
                      [x, y], spec["ids"]), spec, [(w.id, end), (other, oend)])
        else:
            add(Issue("rooms" if ctx.endswith("outside here.") else "dangling", "review",
                      ("Wall end is not connected and no safe connection was found nearby; it may be the edge of a "
                       "doorway or a free-standing partition. " + ctx + " Manual review required.").replace("  ", " ").strip(),
                      [x, y], [w.id], "info" if not ctx else "warning"), None, [])

    # 3. Near-duplicate parallel segments that the automatic pass left alone.
    polys = [wall_polygon(w) for w in walls]
    for i in range(len(walls)):
        for j in range(i + 1, len(walls)):
            a, b = walls[i], walls[j]
            if a.orient not in "hv" or a.orient != b.orient:
                continue
            a0, a1, ac = _axis_extent(a)
            b0, b1, bc = _axis_extent(b)
            ov = min(a1, b1) - max(a0, b0)
            ratio = max(a.thickness, b.thickness) / max(min(a.thickness, b.thickness), 1e-6)
            if ov < 0.3 * min(a1 - a0, b1 - b0) or abs(ac - bc) > 0.6 * max(a.thickness, b.thickness) or ratio > 1.6:
                continue
            if polys[i].distance(polys[j]) > 1.0:
                continue
            short, long_ = (a, b) if a.length <= b.length else (b, a)
            mid = [(max(a0, b0) + min(a1, b1)) / 2, ac] if a.orient == "h" else [ac, (max(a0, b0) + min(a1, b1)) / 2]
            spec = {"kind": "merge_duplicate", "ids": [long_.id, short.id], "a": long_.id, "b": short.id}
            add(Issue("duplicates", "review", "Two overlapping parallel segments look like the same wall drawn twice.",
                      mid, [long_.id, short.id]), spec, [])

    # 4. Oblique crossings (never auto-fixed).
    for i, w in enumerate(walls):
        if w.orient != "d":
            continue
        for j, v in enumerate(walls):
            if j == i:
                continue
            ui, uj = unit(w), unit(v)
            if abs(ui[0] * uj[0] + ui[1] * uj[1]) > 0.96:
                continue
            p = LineString([(w.x1, w.y1), (w.x2, w.y2)]).intersection(LineString([(v.x1, v.y1), (v.x2, v.y2)]))
            if p.is_empty or p.geom_type != "Point":
                continue
            m = [np.hypot(p.x - w.x1, p.y - w.y1), np.hypot(p.x - w.x2, p.y - w.y2),
                 np.hypot(p.x - v.x1, p.y - v.y1), np.hypot(p.x - v.x2, p.y - v.y2)]
            if min(m) > 1.5 * t:
                add(Issue("intersections", "review", "Two walls cross at an oblique angle. Manual review required.",
                          [p.x, p.y], [w.id, v.id]), None, [])

    # 5. Opening context and room enclosure (manual review only).
    for iss in opening_context_issues(walls, openings):
        iss.message += " Manual review required."
        add(iss, None, [])
    if not rooms:
        H, W = labels.shape
        add(Issue("rooms", "review", "No enclosed rooms could be formed from the detected walls. Manual review required.",
                  [W / 2, H / 2], [], "error"), None, [])
    return issues, specs
