"""Wall detection and vectorisation.

Walls in architectural drawings are the thickest continuous ink strokes. We estimate the
stroke-width distribution with a distance transform, keep only strokes at wall thickness
(morphological opening removes text, furniture, dimension lines and door swings), and then
vectorise the remaining mask into rectangular wall segments.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Wall:
    id: str
    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float
    orient: str  # 'h', 'v' or 'd'
    exterior: bool = False
    source: str = "auto"  # 'auto' | 'corrected' | 'edited' (future Fix2Build)
    notes: list[str] = field(default_factory=list)

    @property
    def length(self) -> float:
        return float(np.hypot(self.x2 - self.x1, self.y2 - self.y1))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "x1": round(self.x1, 2), "y1": round(self.y1, 2),
            "x2": round(self.x2, 2), "y2": round(self.y2, 2),
            "thickness": round(self.thickness, 2), "orient": self.orient,
            "exterior": self.exterior, "source": self.source,
        }

    def copy(self) -> "Wall":
        return Wall(self.id, self.x1, self.y1, self.x2, self.y2, self.thickness, self.orient,
                    self.exterior, self.source, list(self.notes))


@dataclass
class WallDetection:
    mask: np.ndarray
    thickness: float
    max_thickness: float
    thin_width: float
    kernel: int
    walls: list[Wall]
    solids: list[dict]
    warnings: list[str]


def estimate_stroke_widths(dark: np.ndarray) -> tuple[float, float, float]:
    """Return (thin line width, interior wall thickness, maximum wall thickness) in pixels."""
    dt = cv2.distanceTransform(dark, cv2.DIST_L2, 5)
    ridge = (dt >= cv2.dilate(dt, np.ones((3, 3), np.float32))) & (dt > 0.9)
    widths = np.round(2 * dt[ridge]).astype(int)
    hist = np.bincount(widths, minlength=120)[:120].astype(float)
    thin_hist = hist[:6]
    thin = float(np.argmax(thin_hist)) if thin_hist.sum() > 0 else 2.0
    thin = max(thin, 1.0)
    lo = int(max(5, round(1.8 * thin)))
    cand = hist.copy()
    cand[:lo] = 0
    if cand.sum() == 0:
        return thin, 0.0, 0.0
    # The smallest significant thick-stroke width is the interior wall thickness.
    peak = cand.max()
    sig = np.where(cand >= 0.15 * peak)[0]
    t = float(sig[0])
    t_max = float(np.where(cand >= 0.08 * peak)[0][-1])
    # Use the weighted mean of the neighbourhood for sub-bin precision.
    nb = np.arange(max(lo, int(t) - 1), int(t) + 2)
    if cand[nb].sum() > 0:
        t = float((nb * cand[nb]).sum() / cand[nb].sum())
    return thin, t, float(min(max(t, t_max), 2.5 * t))


def wall_mask(dark: np.ndarray, thickness: float, text_boxes: list[tuple[int, int, int, int]] | None = None
              ) -> tuple[np.ndarray, int]:
    k = int(max(3, round(0.72 * thickness)))
    kern = np.ones((k, k), np.uint8)
    m = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kern)
    # Re-grow a little so that wall edges keep their original extent.
    m = cv2.bitwise_and(cv2.dilate(m, np.ones((3, 3), np.uint8)), dark)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.ones(n, bool)
    keep[0] = False
    t = thickness
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        longest = max(w, h)
        # Compact blobs (arrows, bold glyphs, symbols) are not walls.
        if longest < 2.6 * t or area < 2.0 * t * t:
            keep[i] = False
            continue
        if text_boxes:
            for (tx, ty, tw, th) in text_boxes:
                pad = 4
                if x >= tx - pad and y >= ty - pad and x + w <= tx + tw + pad and y + h <= ty + th + pad:
                    keep[i] = False
                    break
    return np.where(keep[labels], 255, 0).astype(np.uint8), k


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    return list(zip(starts.tolist(), ends.tolist()))


def _bands(comp: np.ndarray, axis: int, tol: float) -> list[tuple[int, int, int, int]]:
    """Split an axis-aligned component into rectangular bands.

    For horizontal walls (axis=1) we walk rows and group consecutive rows whose runs have a
    similar extent. Returns rectangles (x0, y0, x1, y1), end-exclusive.
    """
    if axis == 0:
        rects = _bands(comp.T, 1, tol)
        return [(y0, x0, y1, x1) for (x0, y0, x1, y1) in rects]
    done: list[list[int]] = []
    active: list[list[int]] = []  # [x0, y0, x1, y1, last_x0, last_x1]
    for r in range(comp.shape[0]):
        runs = _runs(comp[r])
        nxt = []
        used = set()
        for (a, b) in runs:
            match = None
            for j, band in enumerate(active):
                if j in used:
                    continue
                if abs(a - band[4]) <= tol and abs(b - band[5]) <= tol:
                    match = j
                    break
            if match is None:
                nxt.append([a, r, b, r + 1, a, b])
            else:
                used.add(match)
                band = active[match]
                band[0] = min(band[0], a); band[2] = max(band[2], b)
                band[3] = r + 1; band[4], band[5] = a, b
                nxt.append(band)
        for j, band in enumerate(active):
            if j not in used:
                done.append(band)
        active = nxt
    done.extend(active)
    return [tuple(b[:4]) for b in done]


def vectorise(mask: np.ndarray, thickness: float, max_thickness: float) -> tuple[list[Wall], list[dict]]:
    t = thickness
    # The run-length kernel must be longer than the thickest wall so that perpendicular walls vanish.
    L = int(max(2.2 * max_thickness, 2.5 * t, 12))
    horiz = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    vert = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
    walls: list[Wall] = []
    solids: list[dict] = []

    def add_axis(src: np.ndarray, orient: str):
        n, labels, stats, _ = cv2.connectedComponentsWithStats(src, connectivity=4)
        for i in range(1, n):
            x, y, w, h, _ = stats[i]
            comp = (labels[y:y + h, x:x + w] == i)
            rects = _bands(comp, 1 if orient == "h" else 0, tol=max(2.0, 0.5 * t))
            for (rx0, ry0, rx1, ry1) in rects:
                rx0 += x; rx1 += x; ry0 += y; ry1 += y
                rw, rh = rx1 - rx0, ry1 - ry0
                length, thick = (rw, rh) if orient == "h" else (rh, rw)
                if length < 1.6 * t or thick < 0.45 * t:
                    continue
                if thick > max(2.6 * t, 1.5 * max_thickness) and length < 3 * thick:
                    solids.append({"x0": rx0, "y0": ry0, "x1": rx1, "y1": ry1})
                    continue
                if orient == "h":
                    yc = (ry0 + ry1) / 2
                    walls.append(Wall("", rx0, yc, rx1, yc, rh, "h"))
                else:
                    xc = (rx0 + rx1) / 2
                    walls.append(Wall("", xc, ry0, xc, ry1, rw, "v"))

    add_axis(horiz, "h")
    add_axis(vert, "v")

    # Residual (diagonal) walls: what axis-aligned openings could not explain.
    covered = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((5, 5), np.uint8))
    resid = cv2.bitwise_and(mask, cv2.bitwise_not(covered))
    resid = cv2.morphologyEx(resid, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(resid, connectivity=8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 2 * t * t:
            continue
        pts = np.column_stack(np.where(labels == i))[:, ::-1].astype(np.float32)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(pts)
        length, thick = max(rw, rh), min(rw, rh)
        if length < 1.6 * t or thick > max(2.2 * t, 1.3 * max_thickness) or thick < 0.4 * t:
            continue
        theta = np.deg2rad(ang if rw >= rh else ang + 90)
        dx, dy = np.cos(theta) * length / 2, np.sin(theta) * length / 2
        deg = np.rad2deg(theta) % 180
        if min(deg, 180 - deg) < 4:
            walls.append(Wall("", cx - length / 2, cy, cx + length / 2, cy, thick, "h"))
        elif abs(deg - 90) < 4:
            walls.append(Wall("", cx, cy - length / 2, cx, cy + length / 2, thick, "v"))
        else:
            walls.append(Wall("", cx - dx, cy - dy, cx + dx, cy + dy, thick, "d"))

    for i, w in enumerate(walls):
        w.id = f"w{i + 1}"
    return walls, solids


def detect_walls(dark: np.ndarray, text_boxes=None) -> WallDetection:
    warnings: list[str] = []
    thin, t, t_max = estimate_stroke_widths(dark)
    if t <= 0:
        raise ValueError("No wall-thickness strokes were found. The plan may draw walls as thin outlines only.")
    mask, k = wall_mask(dark, t, text_boxes)
    coverage = np.count_nonzero(mask) / mask.size
    if coverage < 0.004:
        raise ValueError("Too little wall structure was found to reconstruct a building.")
    walls, solids = vectorise(mask, t, t_max)
    if len(walls) < 4:
        raise ValueError("Fewer than four wall segments were detected; the image does not look like a floor plan.")
    return WallDetection(mask=mask, thickness=t, max_thickness=t_max, thin_width=thin, kernel=k, walls=walls, solids=solids,
                         warnings=warnings)
