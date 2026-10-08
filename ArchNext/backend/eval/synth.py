"""Synthetic floor-plan generator with exact ground truth.

Produces raster plans in a conventional drafting style (solid walls, door swings, glazed
windows, room names with dimension labels, an overall dimension line and furniture) together
with an annotation in the format accepted by the evaluation endpoint. Typical drawing defects
are injected into the raster only — the annotation always describes the true building:
  * breaks inside straight walls (scan dropouts / broken strokes)
  * interior walls stopping short of the wall they join
  * speckle noise
"""
from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOM_NAMES = [("Bedroom", "bedroom"), ("Bedroom", "bedroom"), ("Kitchen", "kitchen"), ("Living Room", "living"),
              ("Bathroom", "bathroom"), ("Dining", "dining"), ("Study", "study"), ("Hall", "circulation"),
              ("Laundry", "utility")]


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        for name in ("DejaVuSans.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
        return ImageFont.load_default()


def _fmt_len(m: float, imperial: bool) -> str:
    if imperial:
        inches = round(m / 0.0254)
        return f"{inches // 12}'{inches % 12}\""
    return f"{m:.2f}"


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0


def generate(seed: int) -> tuple[bytes, dict]:
    rng = np.random.default_rng(seed)
    s = float(rng.uniform(0.012, 0.019))            # metres per pixel
    Wm, Hm = float(rng.uniform(9, 14)), float(rng.uniform(7, 11))
    ext = 0.25 / s
    it = 0.12 / s
    margin = int(rng.uniform(90, 130))
    W = int(Wm / s + 2 * margin)
    H = int(Hm / s + 2 * margin)
    outer = Rect(margin, margin, margin + Wm / s, margin + Hm / s)
    inner = Rect(outer.x0 + ext, outer.y0 + ext, outer.x1 - ext, outer.y1 - ext)
    imperial = bool(rng.random() < 0.4)

    # Binary space partition into rooms.
    min_room = 2.4 / s
    splits = []  # (orient, coord, a, b) interior wall centre lines
    leaves: list[Rect] = []
    target = int(rng.integers(4, 8))

    def split(r: Rect, depth: int):
        can_v = r.w >= 2 * min_room + it
        can_h = r.h >= 2 * min_room + it
        if depth > 3 or (not can_v and not can_h) or (len(leaves) + 1 >= target and depth > 0 and rng.random() < 0.5):
            leaves.append(r)
            return
        vertical = can_v and (not can_h or r.w >= r.h)
        if vertical:
            c = r.x0 + float(rng.uniform(min_room + it / 2, r.w - min_room - it / 2))
            splits.append(("v", c, r.y0, r.y1))
            split(Rect(r.x0, r.y0, c - it / 2, r.y1), depth + 1)
            split(Rect(c + it / 2, r.y0, r.x1, r.y1), depth + 1)
        else:
            c = r.y0 + float(rng.uniform(min_room + it / 2, r.h - min_room - it / 2))
            splits.append(("h", c, r.x0, r.x1))
            split(Rect(r.x0, r.y0, r.x1, c - it / 2), depth + 1)
            split(Rect(r.x0, c + it / 2, r.x1, r.y1), depth + 1)

    split(inner, 0)

    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    INK = 30
    THIN = 110

    # Walls as filled rectangles.
    wall_rects = [Rect(outer.x0, outer.y0, outer.x1, inner.y0), Rect(outer.x0, inner.y1, outer.x1, outer.y1),
                  Rect(outer.x0, outer.y0, inner.x0, outer.y1), Rect(inner.x1, outer.y0, outer.x1, outer.y1)]
    for o, c, a, b in splits:
        wall_rects.append(Rect(c - it / 2, a, c + it / 2, b) if o == "v" else Rect(a, c - it / 2, b, c + it / 2))
    for r in wall_rects:
        d.rectangle([r.x0, r.y0, r.x1 - 1, r.y1 - 1], fill=INK)

    gt_doors, gt_windows, keepouts = [], [], []

    def door(cx, cy, orient, width, thick, swing_side):
        """Gap + leaf + quarter arc. orient: direction of the wall ('h' or 'v')."""
        if orient == "h":
            x0, x1 = cx - width / 2, cx + width / 2
            d.rectangle([x0, cy - thick / 2 - 1, x1, cy + thick / 2 + 1], fill=255)
            face = cy + swing_side * thick / 2
            d.line([x0, face, x0, face + swing_side * width], fill=THIN, width=2)
            box = [x0 - width, face - width, x0 + width, face + width]
            d.arc(box, 0 if swing_side > 0 else 270, 90 if swing_side > 0 else 360, fill=THIN, width=2)
            gt_doors.append({"x1": x0, "y1": cy, "x2": x1, "y2": cy})
            keepouts.append(Rect(x0 - 4, cy - width - thick, x1 + 4, cy + width + thick))
        else:
            y0, y1 = cy - width / 2, cy + width / 2
            d.rectangle([cx - thick / 2 - 1, y0, cx + thick / 2 + 1, y1], fill=255)
            face = cx + swing_side * thick / 2
            d.line([face, y0, face + swing_side * width, y0], fill=THIN, width=2)
            box = [face - width, y0 - width, face + width, y0 + width]
            d.arc(box, 0 if swing_side > 0 else 90, 90 if swing_side > 0 else 180, fill=THIN, width=2)
            gt_doors.append({"x1": cx, "y1": y0, "x2": cx, "y2": y1})
            keepouts.append(Rect(cx - width - thick, y0 - 4, cx + width + thick, y1 + 4))

    def window(cx, cy, orient, width, thick):
        if orient == "h":
            x0, x1 = cx - width / 2, cx + width / 2
            d.rectangle([x0, cy - thick / 2, x1, cy + thick / 2 - 1], fill=255)
            for off in (-thick / 2, 0, thick / 2 - 1):
                d.line([x0, cy + off, x1, cy + off], fill=THIN, width=1)
            d.line([x0, cy - thick / 2, x0, cy + thick / 2], fill=THIN, width=1)
            d.line([x1, cy - thick / 2, x1, cy + thick / 2], fill=THIN, width=1)
            gt_windows.append({"x1": x0, "y1": cy, "x2": x1, "y2": cy})
            keepouts.append(Rect(x0 - 4, cy - thick, x1 + 4, cy + thick))
        else:
            y0, y1 = cy - width / 2, cy + width / 2
            d.rectangle([cx - thick / 2, y0, cx + thick / 2 - 1, y1], fill=255)
            for off in (-thick / 2, 0, thick / 2 - 1):
                d.line([cx + off, y0, cx + off, y1], fill=THIN, width=1)
            d.line([cx - thick / 2, y0, cx + thick / 2, y0], fill=THIN, width=1)
            d.line([cx - thick / 2, y1, cx + thick / 2, y1], fill=THIN, width=1)
            gt_windows.append({"x1": cx, "y1": y0, "x2": cx, "y2": y1})
            keepouts.append(Rect(cx - thick, y0 - 4, cx + thick, y1 + 4))

    # Interior doors: one per free interval of each split wall.
    for o, c, a, b in splits:
        touches = sorted([c2 for o2, c2, a2, b2 in splits if o2 != o and (abs(a2 - c) <= it or abs(b2 - c) <= it) and a <= c2 <= b])
        bounds = [a] + touches + [b]
        for lo, hi in zip(bounds[:-1], bounds[1:]):
            free = (hi - lo) - it
            dw = float(rng.uniform(0.8, 0.9)) / s
            if free < dw + 0.5 / s:
                continue
            pos = lo + it / 2 + 0.15 / s + dw / 2 + float(rng.uniform(0, max(free - dw - 0.3 / s, 0)))
            side = 1 if rng.random() < 0.5 else -1
            if o == "v":
                door(c, pos, "v", dw, it, side)
            else:
                door(pos, c, "h", dw, it, side)

    # Windows on exterior walls, and one entrance door.
    sides = []
    for r in leaves:
        if abs(r.y0 - inner.y0) < 1:
            sides.append(("h", r.x0, r.x1, outer.y0 + ext / 2, -1))
        if abs(r.y1 - inner.y1) < 1:
            sides.append(("h", r.x0, r.x1, outer.y1 - ext / 2, 1))
        if abs(r.x0 - inner.x0) < 1:
            sides.append(("v", r.y0, r.y1, outer.x0 + ext / 2, -1))
        if abs(r.x1 - inner.x1) < 1:
            sides.append(("v", r.y0, r.y1, outer.x1 - ext / 2, 1))
    entry = int(rng.integers(len(sides)))
    for k, (o, a, b, c, outward) in enumerate(sides):
        span = b - a
        if k == entry and span > 1.6 / s:
            dw = 0.95 / s
            pos = a + span * float(rng.uniform(0.3, 0.7))
            if o == "h":
                door(pos, c, "h", dw, ext, outward)
            else:
                door(c, pos, "v", dw, ext, outward)
            continue
        if span < 1.8 / s:
            continue
        ww = min(float(rng.uniform(1.0, 1.7)) / s, span - 0.8 / s)
        pos = a + span / 2 + float(rng.uniform(-0.15, 0.15)) * (span - ww)
        if o == "h":
            window(pos, c, "h", ww, ext)
        else:
            window(c, pos, "v", ww, ext)

    # Labels and furniture.
    names = list(ROOM_NAMES)
    rng.shuffle(names)
    gt_rooms = []
    fsz = max(13, int(0.28 / s))
    font = _font(fsz)
    small = _font(max(12, int(0.24 / s)))
    for i, r in enumerate(leaves):
        name, typ = names[i % len(names)]
        if i == 0:
            name, typ = "Living Room", "living"
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        wm, hm = r.w * s, r.h * s
        dims = f"{_fmt_len(wm, imperial)} x {_fmt_len(hm, imperial)}" + ("" if imperial else " m")
        tw = d.textlength(name, font=font)
        d.text((cx - tw / 2, cy - fsz * 1.2), name.upper() if rng.random() < 0.5 else name, fill=60, font=font)
        tw2 = d.textlength(dims, font=small)
        d.text((cx - tw2 / 2, cy + 2), dims, fill=60, font=small)
        gt_rooms.append({"polygon": [[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1]], "type": typ, "name": name})
        # furniture (thin lines) away from walls, openings and labels
        for _ in range(int(rng.integers(0, 3))):
            fw, fh = float(rng.uniform(0.6, 1.6)) / s, float(rng.uniform(0.5, 1.2)) / s
            if fw > r.w - 1.2 / s or fh > r.h - 1.2 / s:
                continue
            fx = float(rng.uniform(r.x0 + 0.5 / s, r.x1 - 0.5 / s - fw))
            fy = float(rng.uniform(r.y0 + 0.5 / s, r.y1 - 0.5 / s - fh))
            fr = Rect(fx, fy, fx + fw, fy + fh)
            if abs(fr.x0 + fw / 2 - cx) < fw / 2 + 2.2 / s * 0.5 and abs(fr.y0 + fh / 2 - cy) < fh / 2 + fsz * 2:
                continue
            if any(not (fr.x1 < k.x0 or fr.x0 > k.x1 or fr.y1 < k.y0 or fr.y0 > k.y1) for k in keepouts):
                continue
            if rng.random() < 0.7:
                d.rectangle([fr.x0, fr.y0, fr.x1, fr.y1], outline=THIN, width=2)
            else:
                d.ellipse([fr.x0, fr.y0, fr.x0 + min(fw, fh), fr.y0 + min(fw, fh)], outline=THIN, width=2)

    # Overall dimension line above the building.
    ly = outer.y0 - 45
    d.line([outer.x0, ly, outer.x1, ly], fill=THIN, width=1)
    for x in (outer.x0, outer.x1):
        d.line([x, ly - 8, x, ly + 8], fill=THIN, width=1)
        d.line([x, ly + 10, x, outer.y0 - 8], fill=180, width=1)
    total = _fmt_len(Wm, imperial) + ("" if imperial else " m")
    tw = d.textlength(total, font=small)
    d.rectangle([(outer.x0 + outer.x1) / 2 - tw / 2 - 4, ly - fsz - 2, (outer.x0 + outer.x1) / 2 + tw / 2 + 4, ly - 2], fill=255)
    d.text(((outer.x0 + outer.x1) / 2 - tw / 2, ly - fsz - 2), total, fill=60, font=small)

    # Drawing defects (raster only).
    defects = []

    def clear_of_openings(x0, y0, x1, y1):
        return all(x1 < k.x0 - 6 or x0 > k.x1 + 6 or y1 < k.y0 - 6 or y0 > k.y1 + 6 for k in keepouts)

    for _ in range(int(rng.integers(1, 4))):
        o, c, a, b = splits[int(rng.integers(len(splits)))] if splits and rng.random() < 0.6 else \
            (("h", outer.y0 + ext / 2, outer.x0, outer.x1) if rng.random() < 0.5 else ("v", outer.x0 + ext / 2, outer.y0, outer.y1))
        th = it if (o, c) in [(sp[0], sp[1]) for sp in splits] else ext
        g = float(rng.uniform(0.35, 0.85)) * it
        for _try in range(20):
            p = float(rng.uniform(a + 0.6 / s, b - 0.6 / s))
            box = (p - g / 2, c - th / 2 - 1, p + g / 2, c + th / 2 + 1) if o == "h" else (c - th / 2 - 1, p - g / 2, c + th / 2 + 1, p + g / 2)
            near_junction = any(abs(sp[1] - p) < 0.4 / s for sp in splits if sp[0] != o)
            if clear_of_openings(*box) and not near_junction:
                d.rectangle(list(box), fill=255)
                defects.append({"kind": "wall_break", "at": [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]})
                break
    for o, c, a, b in splits:
        if rng.random() < 0.35:
            g = float(rng.uniform(0.5, 1.2)) * it
            end_a = rng.random() < 0.5
            if o == "v":
                y = a if end_a else b - g
                box = (c - it / 2 - 1, y, c + it / 2 + 1, y + g)
            else:
                x = a if end_a else b - g
                box = (x, c - it / 2 - 1, x + g, c + it / 2 + 1)
            if clear_of_openings(*box):
                d.rectangle(list(box), fill=255)
                defects.append({"kind": "junction_gap", "at": [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]})
    arr = np.array(img)
    noise = rng.random(arr.shape) < 0.0006
    arr[noise] = 70
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.6))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    gt = {"meters_per_px": s, "image_size": [W, H], "rooms": gt_rooms, "doors": gt_doors, "windows": gt_windows,
          "defects": defects, "units": "imperial" if imperial else "metric", "seed": seed}
    return buf.getvalue(), gt


if __name__ == "__main__":
    import sys
    from pathlib import Path
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    out.mkdir(parents=True, exist_ok=True)
    for seed in (int(a) for a in (sys.argv[2:] or ["7", "21"])):
        png, gt = generate(seed)
        (out / f"generated_plan_{seed}.png").write_bytes(png)
        (out / f"generated_plan_{seed}.json").write_text(json.dumps(gt, indent=1))
        print("wrote", out / f"generated_plan_{seed}.png")
