"""TopologyGuard: structural validation and conservative correction of extracted wall geometry.

Every correction is local, bounded by the measured wall thickness and recorded as an issue so
that the original parser output and the corrected geometry can both be inspected and compared.
Gaps that could be real openings are never closed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Point

from .structure import (CONNECT_TOL, JUNCTION_SNAP, MAX_OPENING, MICRO_GAP, MIN_OPENING, end_connected, endpoints,
                        find_gaps, opening_polygon, unit, wall_polygon)
from .walls import Wall

CHECKS = [
    ("duplicates", "Duplicate wall segments", "Overlapping parallel segments that describe the same wall are merged."),
    ("fragments", "Stray wall fragments", "Tiny isolated segments left by symbols, text or noise are removed."),
    ("micro_gaps", "Broken wall lines", "Breaks inside a straight wall that are too narrow to be a door or window are closed."),
    ("junction_gaps", "Junction gaps", "Walls that stop just short of the wall they should meet are extended to it."),
    ("overshoots", "Junction overshoots", "Walls that run slightly past the wall they meet are trimmed."),
    ("intersections", "Suspicious intersections", "Oblique walls crossing other walls are flagged."),
    ("ambiguous_gaps", "Ambiguous gaps", "Gaps too wide for a drawing break but too narrow for a door are left open and flagged."),
    ("dangling", "Disconnected wall ends", "Wall ends not attached to a wall or an opening are flagged."),
    ("openings", "Door and window placement", "Each opening must sit in a valid host wall without overlapping other walls."),
    ("rooms", "Room enclosure", "Spaces whose boundary is not closed by walls and openings are flagged."),
]


@dataclass
class Issue:
    check: str
    status: str            # 'corrected' | 'review' | 'info'
    message: str
    at: list[float]
    walls: list[str] = field(default_factory=list)
    severity: str = "warning"
    fix: dict | None = None    # previewable user fix (review issues only)
    key: str = ""              # stable identifier used to apply a fix

    def to_dict(self, idx: int) -> dict:
        return {"id": f"i{idx}", "key": self.key or f"i{idx}", "check": self.check, "status": self.status,
                "message": self.message, "at": [round(float(self.at[0]), 1), round(float(self.at[1]), 1)],
                "walls": self.walls, "severity": self.severity, "fix": self.fix,
                "fixable": self.fix is not None}


def _axis_extent(w: Wall) -> tuple[float, float, float]:
    """(start, end, centre) along the wall's main axis for h/v walls."""
    if w.orient == "h":
        return min(w.x1, w.x2), max(w.x1, w.x2), (w.y1 + w.y2) / 2
    return min(w.y1, w.y2), max(w.y1, w.y2), (w.x1 + w.x2) / 2


def _make_axis(orient: str, a: float, b: float, c: float, th: float, base: Wall) -> Wall:
    if orient == "h":
        nw = Wall(base.id, a, c, b, c, th, "h", base.exterior, "corrected")
    else:
        nw = Wall(base.id, c, a, c, b, th, "v", base.exterior, "corrected")
    return nw


def _merge_axis(ws: list[Wall]) -> Wall:
    o = ws[0].orient
    lo = min(_axis_extent(w)[0] for w in ws)
    hi = max(_axis_extent(w)[1] for w in ws)
    faces_lo = min(_axis_extent(w)[2] - w.thickness / 2 for w in ws)
    faces_hi = max(_axis_extent(w)[2] + w.thickness / 2 for w in ws)
    th = faces_hi - faces_lo
    if th > 1.35 * max(w.thickness for w in ws):
        # Offset strokes: keep the dominant (longest) wall's band.
        main = max(ws, key=lambda w: w.length)
        c, th = _axis_extent(main)[2], main.thickness
    else:
        c = (faces_lo + faces_hi) / 2
    return _make_axis(o, lo, hi, c, th, ws[0])


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        self.p[self.find(a)] = self.find(b)


def _merge_groups(walls: list[Wall], pairs: list[tuple[int, int]]) -> tuple[list[Wall], dict[int, int]]:
    uf = _UF(len(walls))
    for a, b in pairs:
        uf.union(a, b)
    groups: dict[int, list[int]] = {}
    for i in range(len(walls)):
        groups.setdefault(uf.find(i), []).append(i)
    out: list[Wall] = []
    for root, idx in groups.items():
        if len(idx) == 1:
            out.append(walls[idx[0]])
        else:
            out.append(_merge_axis([walls[i] for i in idx]))
    return out, {}


def run_corrections(raw: list[Wall], t: float) -> tuple[list[Wall], list[Issue]]:
    issues: list[Issue] = []
    walls = [w.copy() for w in raw]

    # 1. Duplicate / overlapping parallel segments.
    pairs = []
    removed = set()
    polys = [wall_polygon(w) for w in walls]
    for i in range(len(walls)):
        for j in range(i + 1, len(walls)):
            a, b = walls[i], walls[j]
            if a.orient in "hv" and a.orient == b.orient:
                a0, a1, ac = _axis_extent(a)
                b0, b1, bc = _axis_extent(b)
                ov = min(a1, b1) - max(a0, b0)
                if abs(ac - bc) <= 0.5 * max(a.thickness, b.thickness) and ov >= 0.5 * min(a1 - a0, b1 - b0):
                    pairs.append((i, j))
                    issues.append(Issue("duplicates", "corrected",
                                        "Two overlapping segments described the same wall and were merged.",
                                        [(max(a0, b0) + min(a1, b1)) / 2 if a.orient == "h" else ac,
                                         ac if a.orient == "h" else (max(a0, b0) + min(a1, b1)) / 2],
                                        [a.id, b.id]))
                    continue
            if polys[i].buffer(-1).within(polys[j].buffer(1)) and i not in removed:
                removed.add(i)
                issues.append(Issue("duplicates", "corrected", "A segment fully contained in another wall was removed.",
                                    list(polys[i].centroid.coords[0]), [a.id, b.id]))
            elif polys[j].buffer(-1).within(polys[i].buffer(1)) and j not in removed:
                removed.add(j)
                issues.append(Issue("duplicates", "corrected", "A segment fully contained in another wall was removed.",
                                    list(polys[j].centroid.coords[0]), [b.id, a.id]))
    pairs = [(a, b) for a, b in pairs if a not in removed and b not in removed]
    keep_idx = [i for i in range(len(walls)) if i not in removed]
    remap = {old: new for new, old in enumerate(keep_idx)}
    walls = [walls[i] for i in keep_idx]
    walls, _ = _merge_groups(walls, [(remap[a], remap[b]) for a, b in pairs])

    # 2. Isolated tiny fragments.
    polys = [wall_polygon(w) for w in walls]
    keep = []
    for i, w in enumerate(walls):
        if w.length < 2.0 * t and w.thickness < 1.4 * t:
            touching = any(polys[i].distance(polys[j]) <= 1.0 for j in range(len(walls)) if j != i)
            if not touching:
                cx, cy = (w.x1 + w.x2) / 2, (w.y1 + w.y2) / 2
                issues.append(Issue("fragments", "corrected", "A tiny isolated wall fragment was removed as drawing noise.",
                                    [cx, cy], [w.id], "info"))
                continue
        keep.append(w)
    walls = keep

    # 3. Micro gaps (collinear) and junction gaps (perpendicular).
    gaps = find_gaps(walls, t, max_mult=MIN_OPENING, corners=False)
    merge_pairs = []
    extensions: dict[tuple[int, int], float] = {}
    for g in gaps:
        a, b = walls[g.a], walls[g.b]
        mid = [(g.sx + g.hx) / 2, (g.sy + g.hy) / 2]
        if g.kind == "collinear":
            if g.dist <= MICRO_GAP * t and a.orient in "hv":
                ratio = max(a.thickness, b.thickness) / max(min(a.thickness, b.thickness), 1e-6)
                if ratio <= 1.6:
                    merge_pairs.append((g.a, g.b))
                else:
                    extensions[(g.a, g.end)] = max(extensions.get((g.a, g.end), 0.0), g.dist + 0.5)
                issues.append(Issue("micro_gaps", "corrected",
                                    f"A {g.dist:.0f}px break in a straight wall was closed (too narrow for an opening).",
                                    mid, [a.id, b.id]))
            elif g.dist < MIN_OPENING * t:
                issues.append(Issue("ambiguous_gaps", "review",
                                    "A narrow gap in a wall was left open: it may be a drawing break or a very narrow opening.",
                                    mid, [a.id, b.id]))
        elif g.kind == "perpendicular":
            if g.dist <= JUNCTION_SNAP * t:
                extensions[(g.a, g.end)] = max(extensions.get((g.a, g.end), 0.0), g.dist + b.thickness / 2)
                issues.append(Issue("junction_gaps", "corrected",
                                    f"A wall stopping {g.dist:.0f}px short of a junction was extended to meet it.",
                                    mid, [a.id, b.id]))
            elif g.dist < MIN_OPENING * t:
                issues.append(Issue("ambiguous_gaps", "review",
                                    "A wall stops short of a junction by more than a drawing tolerance; check whether it should connect.",
                                    mid, [a.id, b.id]))
        else:
            issues.append(Issue("intersections", "review", "A wall meets another wall at an unusual angle.",
                                mid, [a.id, b.id]))
    for (i, end), d in extensions.items():
        w = walls[i]
        ux, uy = unit(w)
        if end == 0:
            w.x1 -= ux * d; w.y1 -= uy * d
        else:
            w.x2 += ux * d; w.y2 += uy * d
        w.source = "corrected"
    walls, _ = _merge_groups(walls, merge_pairs)

    # 4. Overshoots: a wall end poking slightly through a perpendicular wall.
    polys = [wall_polygon(w) for w in walls]
    for i, w in enumerate(walls):
        if w.orient not in "hv":
            continue
        for end in (0, 1):
            x, y, dx, dy = endpoints(w)[end]
            if end_connected(walls, polys, i, end, tol=CONNECT_TOL):
                continue
            for j, v in enumerate(walls):
                if j == i or v.orient not in "hv" or v.orient == w.orient:
                    continue
                v0, v1, vc = _axis_extent(v)
                along = (x if w.orient == "h" else y)
                cross = (y if w.orient == "h" else x)
                if not (v0 - 1 <= cross <= v1 + 1):
                    continue
                far_face = vc + (v.thickness / 2) * (1 if (dx + dy) > 0 else -1)
                e = (along - far_face) * (1 if (dx + dy) > 0 else -1)
                if 0.25 * t < e <= 1.2 * t:
                    if end == 0:
                        w.x1 += -dx * e; w.y1 += -dy * e
                    else:
                        w.x2 -= dx * e; w.y2 -= dy * e
                    w.source = "corrected"
                    issues.append(Issue("overshoots", "corrected",
                                        f"A wall overshooting a junction by {e:.0f}px was trimmed.", [x, y], [w.id, v.id], "info"))
                    break

    # 5. Oblique crossings.
    polys = [wall_polygon(w) for w in walls]
    for i, w in enumerate(walls):
        if w.orient != "d":
            continue
        for j, v in enumerate(walls):
            if j == i:
                continue
            ui, uj = unit(w), unit(v)
            if abs(ui[0] * uj[0] + ui[1] * uj[1]) > 0.96:
                continue
            from shapely.geometry import LineString
            li = LineString([(w.x1, w.y1), (w.x2, w.y2)])
            lj = LineString([(v.x1, v.y1), (v.x2, v.y2)])
            p = li.intersection(lj)
            if p.is_empty or p.geom_type != "Point":
                continue
            px, py = p.x, p.y
            margins = [np.hypot(px - w.x1, py - w.y1), np.hypot(px - w.x2, py - w.y2),
                       np.hypot(px - v.x1, py - v.y1), np.hypot(px - v.x2, py - v.y2)]
            if min(margins) > 1.5 * t:
                issues.append(Issue("intersections", "review", "Two walls cross each other at an oblique angle.",
                                    [px, py], [w.id, v.id]))

    for k, w in enumerate(walls):
        w.id = f"w{k + 1}"
    return walls, issues


def endpoint_report(walls: list[Wall], t: float, openings: list[dict] | None = None
                    ) -> tuple[list[tuple[int, int, float, float]], int, int]:
    """Dangling endpoints (not connected and not ending at an opening) plus totals."""
    polys = [wall_polygon(w) for w in walls]
    op_polys = [opening_polygon(o) for o in (openings or [])]
    dangling = []
    total = 0
    for i, w in enumerate(walls):
        for end in (0, 1):
            total += 1
            if end_connected(walls, polys, i, end, tol=CONNECT_TOL):
                continue
            x, y, _, _ = endpoints(w)[end]
            if any(op.distance(Point(x, y)) <= CONNECT_TOL for op in op_polys):
                continue  # wall meets the jamb or mullion of an opening
            dangling.append((i, end, x, y))
    return dangling, total, total - len(dangling)


def validate_openings(walls: list[Wall], openings: list[dict], t: float) -> tuple[list[dict], list[Issue]]:
    issues: list[Issue] = []
    polys = {w.id: wall_polygon(w) for w in walls}
    valid: list[dict] = []
    for o in openings:
        op = opening_polygon(o)
        shrunk = op.buffer(-1.0)
        cx, cy = op.centroid.x, op.centroid.y
        bad = False
        if shrunk.is_empty:
            bad = True
        else:
            for wid, p in polys.items():
                if wid in o["hosts"]:
                    continue
                if shrunk.intersection(p).area > 0.25 * shrunk.area:
                    bad = True
                    break
        if bad:
            issues.append(Issue("openings", "corrected", f"A {o['type']} overlapping another wall was discarded.",
                                [cx, cy], o["hosts"]))
            continue
        dup = False
        for v in valid:
            vp = opening_polygon(v)
            if op.intersection(vp).area > 0.5 * min(op.area, vp.area):
                dup = True
                break
        if dup:
            issues.append(Issue("openings", "corrected", "A duplicate opening was removed.", [cx, cy], o["hosts"], "info"))
            continue
        valid.append(o)
    return valid, issues


def opening_context_issues(walls: list[Wall], openings: list[dict]) -> list[Issue]:
    ext = {w.id: w.exterior for w in walls}
    issues = []
    for o in openings:
        cx, cy = (o["x1"] + o["x2"]) / 2, (o["y1"] + o["y2"]) / 2
        if o["type"] == "window" and not any(ext.get(h, False) for h in o["hosts"]):
            issues.append(Issue("openings", "review",
                                "Window-like opening on an interior wall: it may be a glazed partition or sliding door.",
                                [cx, cy], o["hosts"]))
        elif o["confidence"] == "low":
            issues.append(Issue("openings", "review", "Opening detected but its type (door or window) is uncertain.",
                                [cx, cy], o["hosts"], "info"))
    return issues


def room_issues(walls: list[Wall], dangling: list[tuple[int, int, float, float]], labels: np.ndarray,
                exterior: np.ndarray, rooms: list[dict], t: float) -> list[Issue]:
    issues: list[Issue] = []
    H, W = labels.shape
    r = int(max(3, 1.5 * t))
    for (i, end, x, y) in dangling:
        x0, x1 = int(max(0, x - r)), int(min(W, x + r + 1))
        y0, y1 = int(max(0, y - r)), int(min(H, y + r + 1))
        ids = set(np.unique(labels[y0:y1, x0:x1]).tolist()) - {0}
        touches_out = bool(exterior[y0:y1, x0:x1].any())
        names = [rooms[k - 1]["name"] or f"Room {k}" for k in sorted(ids)]
        if touches_out and ids:
            msg = f"Open boundary: {', '.join(names)} connects to the outside through an unclosed wall end."
            issues.append(Issue("rooms", "review", msg, [x, y], [walls[i].id]))
        elif touches_out:
            issues.append(Issue("dangling", "review", "Exterior wall end is not connected; the building outline may be open here.",
                                [x, y], [walls[i].id]))
        else:
            issues.append(Issue("dangling", "review", "Free-standing wall end (partition stub or missed junction).",
                                [x, y], [walls[i].id], "info"))
    if not rooms:
        issues.append(Issue("rooms", "review", "No enclosed rooms could be formed from the detected walls.",
                            [W / 2, H / 2], [], "error"))
    return issues


def summarise(issues: list[Issue]) -> list[dict]:
    out = []
    for key, name, desc in CHECKS:
        rel = [i for i in issues if i.check == key]
        out.append({"key": key, "name": name, "description": desc,
                    "detected": len(rel),
                    "corrected": sum(1 for i in rel if i.status == "corrected"),
                    "fixed": sum(1 for i in rel if i.status == "fixed"),
                    "review": sum(1 for i in rel if i.status == "review"),
                    "status": "pass" if not rel else ("review" if any(i.status == "review" for i in rel) else "corrected")})
    return out


def point_in_any(polys, x, y) -> bool:
    p = Point(x, y)
    return any(pp.contains(p) for pp in polys)
