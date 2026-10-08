"""Shared wall geometry helpers and parser-level opening (door / window) detection."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from shapely.geometry import LineString, Point, Polygon

from .walls import Wall

# Gap size thresholds expressed in multiples of the interior wall thickness.
MICRO_GAP = 1.1        # below this a gap cannot be a door or window (drawing break)
MIN_OPENING = 1.9      # smallest gap treated as an opening
MAX_OPENING = 22.0     # larger gaps are open-plan boundaries or missing walls
JUNCTION_SNAP = 1.5    # endpoint short of a perpendicular wall by at most this is snapped
CORNER_OPENING = 8.0   # widest door-sized gap accepted beside an existing junction
WIDE_OPENING = 10.0    # wider gaps must show door or window evidence to count as openings
CONNECT_TOL = 1.5      # pixels: endpoints this close to another wall are connected


def unit(w: Wall) -> tuple[float, float]:
    L = max(w.length, 1e-6)
    return (w.x2 - w.x1) / L, (w.y2 - w.y1) / L


def wall_polygon(w: Wall, extra: float = 0.0) -> Polygon:
    ux, uy = unit(w)
    nx, ny = -uy, ux
    h = w.thickness / 2 + extra
    e = extra
    a = (w.x1 - ux * e, w.y1 - uy * e)
    b = (w.x2 + ux * e, w.y2 + uy * e)
    return Polygon([(a[0] + nx * h, a[1] + ny * h), (b[0] + nx * h, b[1] + ny * h),
                    (b[0] - nx * h, b[1] - ny * h), (a[0] - nx * h, a[1] - ny * h)])


def endpoints(w: Wall) -> list[tuple[float, float, float, float]]:
    """[(x, y, dir_x, dir_y)] for both ends; dir points outward along the wall axis."""
    ux, uy = unit(w)
    return [(w.x1, w.y1, -ux, -uy), (w.x2, w.y2, ux, uy)]


def end_connected(walls: list[Wall], polys: list[Polygon], i: int, end: int, tol: float) -> list[int]:
    x, y, _, _ = endpoints(walls[i])[end]
    p = Point(x, y)
    hits = []
    for j, pj in enumerate(polys):
        if j == i:
            continue
        if pj.distance(p) <= tol:
            hits.append(j)
    return hits


@dataclass
class Gap:
    a: int                 # wall index of the casting endpoint
    end: int               # 0/1 which end of wall a
    b: int                 # wall index hit by the ray
    dist: float            # free distance between the gap start and the hit wall
    kind: str              # 'collinear' | 'perpendicular' | 'oblique'
    sx: float              # gap start (wall end, or far face of the junction it belongs to)
    sy: float
    dx: float              # unit direction of the gap
    dy: float
    corner: bool = False   # gap starts at an already-connected junction (e.g. a door next to a corner)

    @property
    def hx(self) -> float:
        return self.sx + self.dx * self.dist

    @property
    def hy(self) -> float:
        return self.sy + self.dy * self.dist

    def key(self) -> tuple:
        return tuple(sorted((self.a, self.b))) if self.kind == "collinear" and not self.corner else (self.a, self.end, self.b)


def _ray_hits(ray: LineString, x: float, y: float, polys: list[Polygon], skip: set[int]):
    for j, pj in enumerate(polys):
        if j in skip or not ray.intersects(pj):
            continue
        inter = ray.intersection(pj)
        if inter.is_empty:
            continue
        coords = []
        for g in getattr(inter, "geoms", [inter]):
            coords.extend(list(g.coords))
        ds = [np.hypot(cx - x, cy - y) for cx, cy in coords]
        yield j, min(ds), max(ds)


def cast_ray(walls: list[Wall], polys: list[Polygon], i: int, end: int, max_dist: float,
             connected: list[int] | None = None) -> Gap | None:
    x, y, dx, dy = endpoints(walls[i])[end]
    ray = LineString([(x + dx * 0.5, y + dy * 0.5), (x + dx * max_dist, y + dy * max_dist)])
    start = 0.0
    skip = {i}
    if connected:
        # Start beyond the junction this end already belongs to.
        for j, dmin, dmax in _ray_hits(ray, x, y, polys, skip):
            if j in connected and dmin <= CONNECT_TOL + 1:
                start = max(start, dmax)
        skip |= set(connected)
    best = None
    for j, dmin, _ in _ray_hits(ray, x, y, polys, skip):
        if dmin < start - 0.5:
            continue
        if best is None or dmin < best[1]:
            best = (j, dmin)
    if best is None:
        return None
    j, d = best
    wi, wj = walls[i], walls[j]
    ui, uj = unit(wi), unit(wj)
    dot = abs(ui[0] * uj[0] + ui[1] * uj[1])
    if dot > 0.96:
        # Parallel: collinear only if centre lines are close.
        off = abs((wj.x1 - wi.x1) * -ui[1] + (wj.y1 - wi.y1) * ui[0])
        kind = "collinear" if off <= 0.6 * max(wi.thickness, wj.thickness) else "oblique"
    elif dot < 0.2:
        kind = "perpendicular"
    else:
        kind = "oblique"
    return Gap(i, end, j, float(d - start), kind, x + dx * start, y + dy * start, dx, dy, corner=bool(connected))


def find_gaps(walls: list[Wall], t: float, max_mult: float = MAX_OPENING, corners: bool = True) -> list[Gap]:
    polys = [wall_polygon(w) for w in walls]
    gaps: dict[tuple, Gap] = {}
    for i in range(len(walls)):
        if walls[i].thickness > 3 * t:
            continue  # massive elements (chimney breasts, columns) do not frame openings
        for end in (0, 1):
            conn = end_connected(walls, polys, i, end, tol=CONNECT_TOL)
            if conn and not corners:
                continue
            g = cast_ray(walls, polys, i, end, max_mult * t, conn or None)
            if g is None or g.dist <= 0.5:
                continue
            k = g.key()
            if k not in gaps or g.dist < gaps[k].dist:
                gaps[k] = g
    return list(gaps.values())


def _sample(mask: np.ndarray, x: float, y: float) -> bool:
    h, w = mask.shape
    xi, yi = int(round(x)), int(round(y))
    return 0 <= xi < w and 0 <= yi < h and mask[yi, xi] > 0


def _sample_many(mask: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    xi = np.rint(xs).astype(np.int64)
    yi = np.rint(ys).astype(np.int64)
    ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    out = np.zeros(xi.shape, bool)
    out[ok] = mask[yi[ok], xi[ok]] > 0
    return out


def classify_gap(gap: Gap, walls: list[Wall], dark: np.ndarray, dark_dil: np.ndarray) -> dict:
    """Decide whether a gap is a door, window or plain opening from the original ink."""
    wa = walls[gap.a]
    x, y, dx, dy = gap.sx, gap.sy, gap.dx, gap.dy
    nx, ny = -dy, dx
    L = gap.dist
    th = wa.thickness
    # Fill: fraction of positions along the gap where ink crosses the wall band (glazing lines).
    n_pos = max(int(L) - 4, 1)
    along = 2 + np.arange(n_pos) * (L - 4) / max(n_pos - 1, 1)
    across = np.linspace(-th / 2 + 1, th / 2 - 1, max(int(th), 3))
    px = x + dx * along[:, None] + nx * across[None, :]
    py = y + dy * along[:, None] + ny * across[None, :]
    fill = float(_sample_many(dark, px, py).any(axis=1).mean())

    angles = np.deg2rad(np.arange(15, 80, 5))
    cos_a, sin_a = np.cos(angles), np.sin(angles)

    # Door swing: quarter arcs hinged at either end (single leaf) or both ends (double leaf).
    def arc(hx, hy, ax, ay, r, side):
        """Ink on the swing arc minus ink inside the swing area (clutter is not a door)."""
        cx_ = cos_a * ax + sin_a * nx * side
        cy_ = cos_a * ay + sin_a * ny * side
        hits = _sample_many(dark_dil, hx + r * cx_, hy + r * cy_).mean()
        inner = _sample_many(dark, hx + 0.55 * r * cx_, hy + 0.55 * r * cy_).mean()
        return max(0.0, float(hits - inner))

    sx, sy = x, y
    ex, ey = x + dx * L, y + dy * L
    best_arc = 0.0
    for side in (1, -1):
        # Leaves hinge on the wall face (half a thickness off the centre line), sometimes inset by a frame.
        fx, fy = nx * side * th / 2, ny * side * th / 2
        for inset in (0.0, 0.06, 0.12):
            hsx, hsy = sx + dx * inset * L + fx, sy + dy * inset * L + fy
            hex_, hey = ex - dx * inset * L + fx, ey - dy * inset * L + fy
            for f in (0.78, 0.84, 0.9, 0.96, 1.0):
                r = L * (f - inset)
                best_arc = max(best_arc,
                               arc(hsx, hsy, dx, dy, r, side), arc(hex_, hey, -dx, -dy, r, side),
                               (arc(hsx, hsy, dx, dy, r / 2, side) + arc(hex_, hey, -dx, -dy, r / 2, side)) / 2)
    if best_arc >= 0.75:
        typ, conf = "door", "high" if best_arc >= 0.9 else "medium"
    elif fill >= 0.65:
        typ, conf = ("window", "high" if fill >= 0.85 else "medium") if best_arc < 0.6 else ("opening", "low")
    elif best_arc >= 0.6:
        typ, conf = "door", "medium"
    elif fill <= 0.3:
        typ, conf = "opening", "medium"
    else:
        typ, conf = "opening", "low"
    return {"type": typ, "confidence": conf, "fill": round(fill, 3), "swing": round(best_arc, 3),
            "x1": round(sx, 2), "y1": round(sy, 2), "x2": round(ex, 2), "y2": round(ey, 2),
            "width": round(L, 2), "thickness": round(th, 2)}


def detect_openings(walls: list[Wall], gaps: list[Gap], t: float, ink: np.ndarray) -> list[dict]:
    ink_dil = cv2.dilate(ink, np.ones((5, 5), np.uint8))
    cands = []
    for g in gaps:
        if g.kind == "oblique":
            continue
        if not (MIN_OPENING * t <= g.dist <= MAX_OPENING * t):
            continue
        if walls[g.b].thickness > 3 * t:
            continue
        o = classify_gap(g, walls, ink, ink_dil)
        evidence = o["type"] in ("door", "window")
        # Wide gaps need door-swing or glazing evidence; gaps beside an existing junction need a
        # clear door swing of plausible door width.
        if g.dist > WIDE_OPENING * t and not evidence and g.kind != "collinear":
            continue
        if g.corner and g.kind != "collinear":
            strong = (o["type"] == "door" and o["confidence"] == "high") or \
                     (o["type"] == "window" and o["fill"] >= 0.9)
            if not strong and g.dist > CORNER_OPENING * t:
                continue
            if not strong:
                o["type"], o["confidence"] = "opening", "low"
            elif o["type"] == "door" and g.dist > CORNER_OPENING * t:
                continue
        o["hosts"] = [walls[g.a].id, walls[g.b].id]
        o["host_kind"] = g.kind
        o["corner"] = g.corner
        cands.append(o)
    rank = {"high": 2, "medium": 1, "low": 0}
    cands.sort(key=lambda o: (-(o["type"] != "opening"), -rank[o["confidence"]], o["width"]))
    out: list[dict] = []
    for o in cands:
        op = opening_polygon(o)
        if any(op.intersection(opening_polygon(v)).area > 0.5 * min(op.area, opening_polygon(v).area) for v in out):
            continue
        out.append(o)
    out.sort(key=lambda o: (o["y1"], o["x1"]))
    for i, o in enumerate(out):
        o["id"] = f"o{i + 1}"
    return out


def opening_polygon(o: dict) -> Polygon:
    w = Wall("tmp", o["x1"], o["y1"], o["x2"], o["y2"], o["thickness"], "d")
    return wall_polygon(w)
