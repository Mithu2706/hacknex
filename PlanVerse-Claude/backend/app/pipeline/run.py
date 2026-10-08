"""End-to-end floor plan reconstruction pipeline.

upload -> preprocessing -> wall / opening / room detection -> TopologyGuard -> ScaleLock -> result

Two geometry versions are always produced from the same parser output:
  * ``original``  – parser + basic post-processing (the controlled baseline)
  * ``corrected`` – the same, plus TopologyGuard corrections (used for 3D)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import scalelock as sl
from . import topology as tg
from .ocr import TextItem, read_text
from .preprocess import PreparedImage, prepare
from .rooms import extract_rooms
from .structure import MAX_OPENING, detect_openings, find_gaps
from .walls import Wall, detect_walls

PARSER_ID = "opencv-structural-v1"


@dataclass
class GeometryVersion:
    walls: list[Wall]
    openings: list[dict]
    rooms: list[dict]
    labels: np.ndarray
    exterior: np.ndarray
    dangling: list
    endpoints_total: int
    endpoints_ok: int
    solids: list[dict]

    def stats(self) -> dict:
        return {
            "walls": len(self.walls),
            "exterior_walls": sum(1 for w in self.walls if w.exterior),
            "doors": sum(1 for o in self.openings if o["type"] == "door"),
            "windows": sum(1 for o in self.openings if o["type"] == "window"),
            "openings": len(self.openings),
            "rooms": len(self.rooms),
            "dangling_endpoints": len(self.dangling),
            "connected_endpoint_ratio": round(self.endpoints_ok / max(self.endpoints_total, 1), 4),
        }


@dataclass
class PlanSession:
    id: str
    filename: str
    image: PreparedImage
    png: bytes
    texts: list[TextItem]
    ocr_available: bool
    thickness: float
    wall_mask: np.ndarray
    original: GeometryVersion
    corrected: GeometryVersion
    issues: list[tg.Issue]
    measurements: list[dict]
    auto_scale: dict
    scale: dict
    warnings: list[str]
    timings: dict = field(default_factory=dict)
    edited: bool = False   # True once geometry was edited by a user (future Fix2Build)
    created: float = field(default_factory=time.time)


def _mark_exterior(walls: list[Wall], exterior: np.ndarray, t: float) -> None:
    H, W = exterior.shape
    for w in walls:
        L = max(w.length, 1e-6)
        ux, uy = (w.x2 - w.x1) / L, (w.y2 - w.y1) / L
        nx, ny = -uy, ux
        off = w.thickness / 2 + max(3.0, 0.5 * t)
        ext = False
        for f in (0.15, 0.3, 0.5, 0.7, 0.85):
            px, py = w.x1 + (w.x2 - w.x1) * f, w.y1 + (w.y2 - w.y1) * f
            for s in (1, -1):
                xi, yi = int(round(px + nx * off * s)), int(round(py + ny * off * s))
                if not (0 <= xi < W and 0 <= yi < H) or exterior[yi, xi]:
                    ext = True
        w.exterior = ext


def _build_version(walls: list[Wall], solids: list[dict], openings: list[dict], shape, t: float,
                   texts: list[TextItem]) -> GeometryVersion:
    rooms, labels, exterior = extract_rooms(shape, walls, openings, solids, t, texts)
    _mark_exterior(walls, exterior, t)
    dangling, total, ok = tg.endpoint_report(walls, t, openings)
    return GeometryVersion(walls, openings, rooms, labels, exterior, dangling, total, ok, solids)


def process_plan(data: bytes, filename: str = "plan") -> PlanSession:
    timings = {}
    t0 = time.time()
    img = prepare(data)
    timings["preprocess"] = time.time() - t0

    t1 = time.time()
    texts, ocr_ok = read_text(img.rgb)
    timings["ocr"] = time.time() - t1
    text_boxes = [(int(tx.x), int(tx.y), int(tx.w), int(tx.h)) for tx in texts]

    t2 = time.time()
    det = detect_walls(img.dark, text_boxes)
    t = det.thickness
    shape = img.dark.shape
    warnings = list(img.warnings) + list(det.warnings)
    if not ocr_ok:
        warnings.append("Text recognition is unavailable, so room names and automatic scale could not be read.")

    # Baseline: parser output with its own opening detection, no TopologyGuard.
    raw = [w.copy() for w in det.walls]
    raw_openings = detect_openings(raw, find_gaps(raw, t, MAX_OPENING), t, img.soft)
    original = _build_version(raw, det.solids, raw_openings, shape, t, texts)
    timings["parse"] = time.time() - t2

    # TopologyGuard.
    t3 = time.time()
    corr_walls, issues = tg.run_corrections(det.walls, t)
    openings = detect_openings(corr_walls, find_gaps(corr_walls, t, MAX_OPENING), t, img.soft)
    openings, op_issues = tg.validate_openings(corr_walls, openings, t)
    issues += op_issues
    corrected = _build_version(corr_walls, det.solids, openings, shape, t, texts)
    issues += tg.opening_context_issues(corrected.walls, corrected.openings)
    issues += tg.room_issues(corrected.walls, corrected.dangling, corrected.labels, corrected.exterior,
                             corrected.rooms, t)
    timings["topologyguard"] = time.time() - t3

    # ScaleLock.
    t4 = time.time()
    measurements = sl.collect_measurements(texts, corrected.rooms, corrected.labels, img.soft, det.mask)
    extent = _extent_px(corrected.walls)
    cons = sl.consensus(measurements, extent)
    auto_scale = {"scale": cons["scale"], "confidence": cons["confidence"], "accepted": cons["accepted"]}
    if cons["scale"]:
        scale = {"status": "auto", "meters_per_px": cons["scale"], "confidence": cons["confidence"],
                 "basis": f"{len(cons['accepted'])} agreeing dimension label(s) read from the plan"}
    else:
        est = sl.estimate_fallback(corrected.openings, t)
        scale = {"status": "estimated", "meters_per_px": est["scale"], "confidence": None, "basis": est["basis"]}
        warnings.append("No reliable dimension labels were found. Dimensions are estimated; calibrate manually for accurate sizes.")
    timings["scalelock"] = time.time() - t4

    ok, buf = cv2.imencode(".png", cv2.cvtColor(img.rgb, cv2.COLOR_RGB2BGR))
    sess = PlanSession(id=uuid.uuid4().hex[:12], filename=filename, image=img, png=buf.tobytes(), texts=texts,
                       ocr_available=ocr_ok, thickness=t, wall_mask=det.mask, original=original,
                       corrected=corrected, issues=issues, measurements=measurements, auto_scale=auto_scale,
                       scale=scale, warnings=warnings, timings=timings)
    if not corrected.rooms:
        warnings.append("No enclosed rooms were found; the model shows walls only.")
    return sess


def rebuild_from_walls(sess: PlanSession, walls: list[Wall]) -> None:
    """Regenerate openings, rooms and checks from user-edited walls (Fix2Build hook).

    Edited sessions are flagged so that they are never counted in automatic accuracy scores.
    """
    t = sess.thickness
    img = sess.image
    for w in walls:
        w.source = "edited"
    openings = detect_openings(walls, find_gaps(walls, t, MAX_OPENING), t, img.soft)
    openings, op_issues = tg.validate_openings(walls, openings, t)
    sess.corrected = _build_version(walls, sess.corrected.solids, openings, img.dark.shape, t, sess.texts)
    sess.issues = op_issues + tg.opening_context_issues(walls, openings) + tg.room_issues(
        walls, sess.corrected.dangling, sess.corrected.labels, sess.corrected.exterior, sess.corrected.rooms, t)
    sess.edited = True


def _extent_px(walls: list[Wall]) -> float:
    xs = [v for w in walls for v in (w.x1, w.x2)]
    ys = [v for w in walls for v in (w.y1, w.y2)]
    return float(max(max(xs) - min(xs), max(ys) - min(ys))) if xs else 0.0


def apply_manual_scale(sess: PlanSession, p1, p2, meters: float) -> None:
    s = sl.manual_scale(p1, p2, meters)
    sess.scale = {"status": "manual", "meters_per_px": s, "confidence": None,
                  "basis": f"two points {np.hypot(p2[0]-p1[0], p2[1]-p1[1]):.0f}px apart set to {meters:.3f} m",
                  "points": [p1, p2], "meters": meters}


def reset_scale(sess: PlanSession) -> None:
    if sess.auto_scale["scale"]:
        sess.scale = {"status": "auto", "meters_per_px": sess.auto_scale["scale"],
                      "confidence": sess.auto_scale["confidence"],
                      "basis": f"{len(sess.auto_scale['accepted'])} agreeing dimension label(s) read from the plan"}
    else:
        est = sl.estimate_fallback(sess.corrected.openings, sess.thickness)
        sess.scale = {"status": "estimated", "meters_per_px": est["scale"], "confidence": None, "basis": est["basis"]}


# ---------------------------------------------------------------- serialisation

def _room_out(r: dict, s: float) -> dict:
    out = {k: r[k] for k in ("id", "name", "type", "polygon", "centroid", "rectangularity", "label_texts")}
    out["name"] = r["name"] or f"Room {r['id'][1:]}"
    out["named"] = r["name"] is not None
    out["area_m2"] = round(r["area_px"] * s * s, 2)
    out["length_m"] = round(r["rect_px"][0] * s, 2)
    out["width_m"] = round(r["rect_px"][1] * s, 2)
    out["label_dims"] = r["label_dims"]["text"] if r["label_dims"] else None
    return out


def _version_out(v: GeometryVersion, s: float) -> dict:
    return {
        "walls": [w.to_dict() for w in v.walls],
        "openings": [{k: o[k] for k in ("id", "type", "confidence", "x1", "y1", "x2", "y2", "width", "thickness", "hosts")}
                     for o in v.openings],
        "rooms": [_room_out(r, s) for r in v.rooms],
        "solids": v.solids,
        "dangling": [[round(x, 1), round(y, 1)] for (_, _, x, y) in v.dangling],
        "stats": v.stats(),
    }


def _plain(o):
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, np.generic):
        return o.item()
    return o


def session_result(sess: PlanSession) -> dict:
    return _plain(_session_result(sess))


def _session_result(sess: PlanSession) -> dict:
    s = sess.scale["meters_per_px"]
    H, W = sess.image.dark.shape
    issues = [i.to_dict(k + 1) for k, i in enumerate(sess.issues)]
    measurements = []
    for m in sess.measurements:
        measurements.append({
            "text": m["text"], "kind": m["kind"], "bbox": m["bbox"], "status": m["status"], "reason": m["reason"],
            "room": m["room"], "line": m["line"],
            "meters": m.get("chosen", {}).get("meters"),
            "unit": m.get("chosen", {}).get("unit"),
            "scale": m.get("chosen", {}).get("scale"),
        })
    loo = sl.leave_one_out(sess.measurements, sess.auto_scale["accepted"]) if sess.auto_scale["scale"] else []
    return {
        "id": sess.id,
        "filename": sess.filename,
        "image": {"width": W, "height": H, "url": f"/api/plans/{sess.id}/image"},
        "wall_thickness_px": round(sess.thickness, 2),
        "scale": {**{k: v for k, v in sess.scale.items()}, "meters_per_px": s,
                  "wall_thickness_m": round(sess.thickness * s, 3),
                  "extent_m": [round(W * s, 2), round(H * s, 2)],
                  "auto_available": bool(sess.auto_scale["scale"]),
                  "auto_meters_per_px": sess.auto_scale["scale"],
                  "measurements": measurements, "holdout": loo,
                  "assumptions": {"wall_height_m": sl.DEFAULT_WALL_HEIGHT_M, "door_height_m": sl.DEFAULT_DOOR_HEIGHT_M,
                                  "window_sill_m": sl.DEFAULT_SILL_M, "window_head_m": sl.DEFAULT_HEAD_M}},
        "geometry": {"original": _version_out(sess.original, s), "corrected": _version_out(sess.corrected, s)},
        "topology": {"checks": tg.summarise(sess.issues), "issues": issues,
                     "corrected": sum(1 for i in sess.issues if i.status == "corrected"),
                     "review": sum(1 for i in sess.issues if i.status == "review")},
        "texts": [t.to_dict() for t in sess.texts],
        "warnings": [w for w in sess.warnings
                     if not (sess.scale["status"] != "estimated" and w.startswith("No reliable dimension labels"))],
        "ocr_available": sess.ocr_available,
    }
