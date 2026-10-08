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
from . import fixes as fx
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
    edited: bool = False   # True once the user applied a geometry fix
    data: bytes = b""
    config: dict = field(default_factory=dict)
    auto_version: "GeometryVersion | None" = None   # automatic result, used for evaluation
    auto_issues: list = field(default_factory=list)
    auto_scale_initial: dict = field(default_factory=dict)
    fix_specs: dict = field(default_factory=dict)
    fix_log: list = field(default_factory=list)
    history: list = field(default_factory=list)
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
    # Conservative classification: glazing-like gaps on purely interior walls are far more often
    # sliding doors, glazed partitions or door frames than windows, so they are not called windows.
    ext = {w.id for w in walls if w.exterior}
    for o in openings:
        if o["type"] == "window" and not any(h in ext for h in o["hosts"]):
            o["type"], o["confidence"] = "opening", "low"
    dangling, total, ok = tg.endpoint_report(walls, t, openings)
    return GeometryVersion(walls, openings, rooms, labels, exterior, dangling, total, ok, solids)


def _auto_scale(texts, version: GeometryVersion, img: PreparedImage, wall_mask, t: float):
    measurements = sl.collect_measurements(texts, version.rooms, version.labels, img.soft, wall_mask)
    cons = sl.consensus(measurements, _extent_px(version.walls))
    return measurements, {"scale": cons["scale"], "confidence": cons["confidence"], "accepted": cons["accepted"]}


def _scale_from(auto_scale: dict, version: GeometryVersion, t: float) -> dict:
    if auto_scale["scale"]:
        return {"status": "auto", "meters_per_px": auto_scale["scale"], "confidence": auto_scale["confidence"],
                "basis": f"{len(auto_scale['accepted'])} agreeing dimension label(s) read from the plan"}
    est = sl.estimate_fallback(version.openings, t)
    return {"status": "estimated", "meters_per_px": est["scale"], "confidence": None, "basis": est["basis"]}


def process_plan(data: bytes, filename: str = "plan", topology_guard: bool = True,
                 scale_lock: bool = True) -> PlanSession:
    """Run the reconstruction pipeline.

    ``topology_guard`` and ``scale_lock`` switch the two contributions on or off independently; the
    parser, preprocessing and OCR are identical in every configuration (used by the ablation study).
    """
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

    # TopologyGuard (automatic, conservative corrections).
    t3 = time.time()
    auto_issues: list[tg.Issue] = []
    if topology_guard:
        corr_walls, issues = tg.run_corrections(det.walls, t)
        openings = detect_openings(corr_walls, find_gaps(corr_walls, t, MAX_OPENING), t, img.soft)
        openings, op_issues = tg.validate_openings(corr_walls, openings, t)
        auto_issues = [i for i in issues + op_issues if i.status == "corrected"]
        corrected = _build_version(corr_walls, det.solids, openings, shape, t, texts)
    else:
        corrected = original
    timings["topologyguard"] = time.time() - t3

    # ScaleLock.
    t4 = time.time()
    if scale_lock:
        measurements, auto_scale = _auto_scale(texts, corrected, img, det.mask, t)
    else:
        measurements, auto_scale = [], {"scale": None, "confidence": None, "accepted": []}
    scale = _scale_from(auto_scale, corrected, t)
    if scale["status"] == "estimated":
        warnings.append("No reliable dimension labels were found. Dimensions are estimated; calibrate manually for accurate sizes.")
    timings["scalelock"] = time.time() - t4

    ok, buf = cv2.imencode(".png", cv2.cvtColor(img.rgb, cv2.COLOR_RGB2BGR))
    sess = PlanSession(id=uuid.uuid4().hex[:12], filename=filename, image=img, png=buf.tobytes(), texts=texts,
                       ocr_available=ocr_ok, thickness=t, wall_mask=det.mask, original=original,
                       corrected=corrected, issues=[], measurements=measurements, auto_scale=auto_scale,
                       scale=scale, warnings=warnings, timings=timings)
    sess.data = data
    sess.config = {"topology_guard": topology_guard, "scale_lock": scale_lock}
    sess.auto_version = corrected
    sess.auto_issues = auto_issues
    sess.auto_scale_initial = dict(auto_scale)
    refresh_issues(sess)
    if not corrected.rooms:
        warnings.append("No enclosed rooms were found; the model shows walls only.")
    return sess


# ------------------------------------------------------------- user fixes (Fix2Build, step 1)

def refresh_issues(sess: PlanSession) -> None:
    """Recompute the remaining (review) issues on the current geometry."""
    v = sess.corrected
    live, specs = fx.detect_review_issues(v.walls, v.openings, sess.thickness, sess.image.soft,
                                          v.labels, v.exterior, v.rooms)
    sess.fix_specs = specs
    fixed = [tg.Issue(f["check"], "fixed", f["message"], f["at"], f["walls"], "info") for f in sess.fix_log]
    sess.issues = list(sess.auto_issues) + fixed + live


def _rebuild(sess: PlanSession, walls: list[Wall]) -> GeometryVersion:
    t = sess.thickness
    img = sess.image
    openings = detect_openings(walls, find_gaps(walls, t, MAX_OPENING), t, img.soft)
    openings, _ = tg.validate_openings(walls, openings, t)
    return _build_version(walls, sess.corrected.solids, openings, img.dark.shape, t, sess.texts)


def apply_user_fix(sess: PlanSession, key: str) -> dict:
    """Apply the fix attached to a review issue. Returns a short report."""
    issue = next((i for i in sess.issues if i.key == key and i.status == "review"), None)
    spec = sess.fix_specs.get(key)
    if issue is None or spec is None:
        raise KeyError("This issue has no safe fix available (it may already be resolved).")
    new_walls = fx.apply_fix(sess.corrected.walls, spec)
    sess.history.append((sess.corrected, list(sess.fix_log), sess.measurements, dict(sess.auto_scale), dict(sess.scale)))
    del sess.history[:-20]
    sess.corrected = _rebuild(sess, new_walls)
    if sess.config.get("scale_lock", True):
        sess.measurements, sess.auto_scale = _auto_scale(sess.texts, sess.corrected, sess.image, sess.wall_mask,
                                                         sess.thickness)
    if sess.scale["status"] != "manual":
        sess.scale = _scale_from(sess.auto_scale, sess.corrected, sess.thickness)
    label = fx.FIX_LABEL[spec["kind"]]
    sess.fix_log.append({"check": issue.check, "message": f"{label}: {issue.message.split(' Manual')[0]}",
                         "at": issue.at, "walls": issue.walls, "kind": spec["kind"]})
    sess.edited = True
    refresh_issues(sess)
    still = any(i.key == key and i.status == "review" for i in sess.issues)
    return {"applied": label, "resolved": not still}


def undo_user_fix(sess: PlanSession) -> None:
    if not sess.history:
        raise KeyError("There is nothing to undo.")
    sess.corrected, sess.fix_log, sess.measurements, sess.auto_scale, scale = sess.history.pop()
    if sess.scale["status"] != "manual":
        sess.scale = scale
    sess.edited = bool(sess.fix_log)
    refresh_issues(sess)


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
    sess.scale = _scale_from(sess.auto_scale, sess.corrected, sess.thickness)


def _scale_checks(sess: PlanSession) -> tuple[list[dict], list[str]]:
    """Written-vs-predicted label comparison for the CURRENT calibration method, plus warnings."""
    s = sess.scale["meters_per_px"]
    status = sess.scale["status"]
    rows: list[dict] = []
    if status == "auto":
        rows = [{**r, "method": "automatic"} for r in sl.leave_one_out(sess.measurements, sess.auto_scale["accepted"])]
    elif status == "manual":
        for m in sess.measurements:
            if "chosen" not in m:
                continue
            for lab, p in zip(m["chosen"]["meters"], sorted(m["px"], reverse=True)):
                pred = p * s
                rows.append({"text": m["text"], "labelled_m": round(lab, 3), "predicted_m": round(pred, 3),
                             "error_pct": round(abs(pred - lab) / lab * 100, 2), "method": "manual"})
    warns = []
    th = sess.thickness * s
    if not (0.05 <= th <= 0.6):
        warns.append(f"The resulting wall thickness ({th:.2f} m) is unrealistic; check the calibration.")
    ext = _extent_px(sess.corrected.walls) * s
    if ext > 150 or ext < 3:
        warns.append(f"The resulting building size ({ext:.1f} m across) is implausible for a floor plan.")
    if status == "manual":
        p1, p2 = sess.scale["points"]
        px = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
        if px < 60:
            warns.append("The two reference points are very close together; small click errors cause large scale errors.")
        if sess.scale["meters"] < 0.5:
            warns.append("The reference distance is very short; use a full wall length for a more accurate scale.")
    return rows, warns


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
    loo, scale_warnings = _scale_checks(sess)
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
                  "measurements": measurements, "holdout": loo, "warnings": scale_warnings,
                  "assumptions": {"wall_height_m": sl.DEFAULT_WALL_HEIGHT_M, "door_height_m": sl.DEFAULT_DOOR_HEIGHT_M,
                                  "window_sill_m": sl.DEFAULT_SILL_M, "window_head_m": sl.DEFAULT_HEAD_M}},
        "geometry": {"original": _version_out(sess.original, s), "corrected": _version_out(sess.corrected, s)},
        "topology": {"checks": tg.summarise(sess.issues), "issues": issues,
                     "corrected": sum(1 for i in sess.issues if i.status == "corrected"),
                     "fixed": sum(1 for i in sess.issues if i.status == "fixed"),
                     "review": sum(1 for i in sess.issues if i.status == "review"),
                     "fixable": sum(1 for i in sess.issues if i.status == "review" and i.fix),
                     "can_undo": bool(sess.history), "edited": sess.edited},
        "texts": [t.to_dict() for t in sess.texts],
        "warnings": [w for w in sess.warnings
                     if not (sess.scale["status"] != "estimated" and w.startswith("No reliable dimension labels"))],
        "ocr_available": sess.ocr_available,
    }
