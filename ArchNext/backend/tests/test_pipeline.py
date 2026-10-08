import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline.measure import parse_dimension
from app.pipeline.run import process_plan, session_result
from app.pipeline.structure import find_gaps
from app.pipeline.topology import run_corrections
from app.pipeline.walls import Wall
from eval.synth import generate

client = TestClient(app)


@pytest.fixture(scope="module")
def plan_a():
    return generate(3)


@pytest.fixture(scope="module")
def plan_b():
    return generate(7)


def test_dimension_parsing():
    p = parse_dimension("10'1\" x 11'1\"")
    assert p["kind"] == "pair" and abs(p["lengths"][0].meters - 3.0734) < 1e-3
    p = parse_dimension("3.45 x 4.10 m")
    assert [round(l.meters, 2) for l in p["lengths"]] == [3.45, 4.1]
    p = parse_dimension("322X347")
    assert p["kind"] == "pair" and p["lengths"][0].unit is None
    assert parse_dimension("BEDROOM") is None
    assert parse_dimension("18") is None
    assert parse_dimension("11'7\" x 157*") is None  # mixed units from an OCR misread are rejected


def test_topology_guard_closes_breaks_but_keeps_openings():
    t = 10.0
    walls = [
        Wall("a", 0, 0, 200, 0, t, "h"),
        Wall("b", 206, 0, 400, 0, t, "h"),        # 6px break: drawing defect
        Wall("c", 460, 0, 700, 0, t, "h"),        # 60px gap: a door-sized opening
    ]
    fixed, issues = run_corrections(walls, t)
    assert len(fixed) == 2, "micro gap should be merged"
    assert any(i.check == "micro_gaps" and i.status == "corrected" for i in issues)
    gaps = find_gaps(fixed, t)
    assert any(abs(g.dist - 60) < 2 for g in gaps), "door gap must be preserved"


def test_end_to_end_synthetic(plan_a):
    png, gt = plan_a
    sess = process_plan(png, "a.png")
    res = session_result(sess)
    corr = res["geometry"]["corrected"]
    orig = res["geometry"]["original"]
    assert len(corr["walls"]) >= 4
    assert len(corr["rooms"]) >= len(gt["rooms"]) - 1
    assert corr["stats"]["rooms"] >= orig["stats"]["rooms"]
    assert res["scale"]["status"] == "auto"
    true_scale = gt["meters_per_px"] / sess.image.resample
    assert abs(res["scale"]["meters_per_px"] - true_scale) / true_scale < 0.03
    assert corr["stats"]["doors"] >= 1 and corr["stats"]["windows"] >= 1


def test_different_plans_give_different_geometry(plan_a, plan_b):
    ra = session_result(process_plan(plan_a[0]))
    rb = session_result(process_plan(plan_b[0]))
    wa = {(round(w["x1"]), round(w["y1"])) for w in ra["geometry"]["corrected"]["walls"]}
    wb = {(round(w["x1"]), round(w["y1"])) for w in rb["geometry"]["corrected"]["walls"]}
    assert wa != wb
    assert len(ra["geometry"]["corrected"]["rooms"]) != len(rb["geometry"]["corrected"]["rooms"]) or \
        ra["image"] != rb["image"]


def test_api_upload_calibrate_and_evaluate(plan_a):
    png, gt = plan_a
    r = client.post("/api/plans", files={"file": ("plan.png", png, "image/png")})
    assert r.status_code == 200
    d = r.json()
    room0 = d["geometry"]["corrected"]["rooms"][0]
    # Manual calibration: double the scale -> room dimensions double.
    s = d["scale"]["meters_per_px"]
    r2 = client.post(f"/api/plans/{d['id']}/calibration",
                     json={"p1": [0, 0], "p2": [100, 0], "distance": 200 * s, "unit": "m"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["scale"]["status"] == "manual"
    assert abs(d2["geometry"]["corrected"]["rooms"][0]["length_m"] - 2 * room0["length_m"]) < 0.05
    # Manual calibration is never reported as automatic.
    assert d2["scale"]["holdout"] and all(r["method"] == "manual" for r in d2["scale"]["holdout"])
    # An unrealistic reference distance is flagged.
    bad = client.post(f"/api/plans/{d['id']}/calibration",
                      json={"p1": [0, 0], "p2": [30, 0], "distance": 0.06, "unit": "m"}).json()
    assert any("close together" in w for w in bad["scale"]["warnings"])
    assert any("wall thickness" in w for w in bad["scale"]["warnings"])
    r3 = client.delete(f"/api/plans/{d['id']}/calibration")
    assert r3.json()["scale"]["status"] == "auto"
    assert all(r["method"] == "automatic" for r in r3.json()["scale"]["holdout"])
    import json
    r4 = client.post(f"/api/plans/{d['id']}/evaluate", files={"file": ("gt.json", json.dumps(gt), "application/json")})
    assert r4.status_code == 200
    ev = r4.json()
    cfg = ev["configs"]
    assert set(cfg) == {"baseline", "topologyguard_only", "scalelock_only", "full"}
    assert cfg["full"]["room_recall"] >= cfg["baseline"]["room_recall"]
    assert cfg["full"]["scale_method"] == "automatic" and cfg["baseline"]["scale_method"] == "estimated"
    assert client.get(f"/api/plans/{d['id']}/image").status_code == 200


def _png(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def test_invalid_uploads():
    assert client.post("/api/plans", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 400
    assert client.post("/api/plans", files={"file": ("s.png", _png(np.full((50, 50), 255, np.uint8)), "image/png")}).status_code == 400
    blank = _png(np.full((600, 800), 255, np.uint8))
    assert client.post("/api/plans", files={"file": ("b.png", blank, "image/png")}).status_code == 400
    assert client.get("/api/plans/doesnotexist").status_code == 404
