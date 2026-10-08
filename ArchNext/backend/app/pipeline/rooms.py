"""Enclosed room extraction from vector walls and sealed openings."""
from __future__ import annotations

import re

import cv2
import numpy as np

from .measure import parse_dimension
from .ocr import TextItem
from .structure import opening_polygon, wall_polygon
from .walls import Wall

ROOM_TYPES = [
    ("bathroom", ["bath", "shower", "wc", "toilet", "ensuite", "en-suite", "powder", "lavatory", "restroom"]),
    ("bedroom", ["bed", "master", "guest room", "nursery", "suite"]),
    ("kitchen", ["kitchen", "kitchenette", "pantry", "kit"]),
    ("living", ["living", "lounge", "family", "sitting", "great room", "theatre", "theater", "media", "activity", "rumpus"]),
    ("dining", ["dining", "dinning", "meals"]),
    ("circulation", ["hall", "foyer", "entry", "entrance", "landing", "corridor", "lobby", "passage", "gallery", "stair"]),
    ("garage", ["garage", "carport"]),
    ("outdoor", ["terrace", "balcony", "patio", "deck", "porch", "alfresco", "veranda", "verandah", "courtyard"]),
    ("study", ["study", "office", "den", "library", "nook"]),
    ("utility", ["laundry", "utility", "storage", "store", "closet", "wardrobe", "robe", "wir", "linen", "mud", "boiler", "plant"]),
]


def room_type_for(name: str) -> str:
    n = name.lower()
    for typ, keys in ROOM_TYPES:
        for k in keys:
            if re.search(rf"\b{re.escape(k)}", n):
                return typ
    return "unknown"


def rasterise(shape: tuple[int, int], walls: list[Wall], openings: list[dict], solids: list[dict]) -> np.ndarray:
    m = np.zeros(shape, np.uint8)
    for w in walls:
        pts = np.array(wall_polygon(w).exterior.coords[:-1], np.float32)
        cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255)
    for o in openings:
        pts = np.array(opening_polygon(o).exterior.coords[:-1], np.float32)
        cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255)
    for s in solids:
        cv2.rectangle(m, (int(s["x0"]), int(s["y0"])), (int(s["x1"]) - 1, int(s["y1"]) - 1), 255, -1)
    return m


def extract_rooms(shape: tuple[int, int], walls: list[Wall], openings: list[dict], solids: list[dict],
                  t: float, texts: list[TextItem]) -> tuple[list[dict], np.ndarray, np.ndarray]:
    """Return (rooms, label image, exterior mask)."""
    sealed = rasterise(shape, walls, openings, solids)
    free = cv2.bitwise_not(sealed)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    H, W = shape
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])).tolist())
    exterior = np.isin(labels, list(border)) & (free > 0)
    min_area = max(30 * t * t, 0.0008 * H * W)
    rooms = []
    room_labels = np.zeros(shape, np.int32)
    for i in range(1, n):
        if i in border:
            continue
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        comp = (labels == i).astype(np.uint8)
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnt = max(cnts, key=cv2.contourArea)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(cnt)
        if min(rw, rh) < 2.2 * t:
            continue
        approx = cv2.approxPolyDP(cnt, max(1.5, 0.3 * t), True).reshape(-1, 2)
        rid = len(rooms) + 1
        room_labels[labels == i] = rid
        x, y, bw, bh = cv2.boundingRect(cnt)
        rooms.append({
            "id": f"r{rid}", "polygon": [[int(px), int(py)] for px, py in approx],
            "area_px": area, "centroid": [round(float(cx), 1), round(float(cy), 1)],
            "rect_px": [round(float(max(rw, rh)), 1), round(float(min(rw, rh)), 1)],
            "bbox": [int(x), int(y), int(bw), int(bh)],
            "rectangularity": round(area / max(rw * rh, 1.0), 3),
            "name": None, "type": "unknown", "label_texts": [], "label_dims": None,
        })
    _attach_labels(rooms, room_labels, texts)
    return rooms, room_labels, exterior


def _attach_labels(rooms: list[dict], room_labels: np.ndarray, texts: list[TextItem]) -> None:
    H, W = room_labels.shape
    by_room: dict[int, list[TextItem]] = {}
    for tx in texts:
        xi, yi = int(round(tx.cx)), int(round(tx.cy))
        if not (0 <= xi < W and 0 <= yi < H):
            continue
        rid = int(room_labels[yi, xi])
        if rid == 0:
            continue
        by_room.setdefault(rid, []).append(tx)
    for rid, items in by_room.items():
        room = rooms[rid - 1]
        items.sort(key=lambda t: (t.y, t.x))
        names = []
        for it in items:
            dim = parse_dimension(it.text)
            if dim and dim["kind"] == "pair" and room["label_dims"] is None:
                room["label_dims"] = {"text": it.text, "bbox": [it.x, it.y, it.w, it.h]}
                continue
            if dim:
                continue
            word = it.text.strip()
            letters = sum(ch.isalpha() for ch in word)
            if letters < 2:
                continue
            if room_type_for(word) != "unknown" or (it.score >= 0.75 and letters >= 3):
                names.append(word)
        room["label_texts"] = [it.text for it in items]
        if names:
            name = " / ".join(names[:2])
            room["name"] = name.title() if name.isupper() else name
            room["type"] = room_type_for(name)
