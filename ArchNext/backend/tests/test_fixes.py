"""TopologyGuard user fixes: apply changes real geometry, rooms and checks; undo restores them."""
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app
from app.pipeline.run import apply_user_fix, process_plan, session_result, undo_user_fix

client = TestClient(app)
T = 14  # wall thickness in px


def _plan(short_gap: int, door_arc: bool = False) -> bytes:
    """A two-room plan whose dividing wall stops `short_gap` px short of the exterior wall."""
    img = Image.new("L", (1200, 900), 255)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 150, 150, 1050, 750
    for r in [(x0, y0, x1, y0 + T), (x0, y1 - T, x1, y1), (x0, y0, x0 + T, y1), (x1 - T, y0, x1, y1)]:
        d.rectangle(r, fill=20)
    cx = 600
    d.rectangle((cx - T // 2, y0 + T + short_gap, cx + T // 2, y1 - T), fill=20)
    if door_arc:
        d.arc((cx - short_gap, y0 + T - short_gap, cx + short_gap, y0 + T + short_gap), 0, 90, fill=90, width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fixable(sess, kind=None):
    return [i for i in sess.issues if i.status == "review" and i.fix and (kind is None or i.fix["kind"] == kind)]


def test_fix_connects_wall_updates_rooms_and_undo_restores():
    sess = process_plan(_plan(short_gap=2 * T))
    before = session_result(sess)
    assert before["geometry"]["corrected"]["stats"]["rooms"] == 1  # the gap merges the two rooms
    fixes = _fixable(sess, "connect")
    assert fixes, "a narrow junction gap should offer a safe Connect fix"
    issue = fixes[0]
    target = issue.fix["after"][0]
    report = apply_user_fix(sess, issue.key)
    after = session_result(sess)
    # Real geometry changed: the wall now reaches the exterior wall and two rooms exist.
    moved = next(w for w in after["geometry"]["corrected"]["walls"] if w["id"] == target["id"])
    assert (moved["x1"], moved["y1"], moved["x2"], moved["y2"]) == (target["x1"], target["y1"], target["x2"], target["y2"])
    assert moved["source"] == "edited"
    assert after["geometry"]["corrected"]["stats"]["rooms"] == 2
    assert report["resolved"] is True
    assert after["topology"]["fixed"] == 1 and after["topology"]["can_undo"]
    assert not any(i["key"] == issue.key and i["status"] == "review" for i in after["topology"]["issues"])
    # Undo restores the previous geometry exactly.
    undo_user_fix(sess)
    restored = session_result(sess)
    assert restored["geometry"]["corrected"]["walls"] == before["geometry"]["corrected"]["walls"]
    assert restored["geometry"]["corrected"]["stats"]["rooms"] == 1
    assert restored["topology"]["fixed"] == 0 and not restored["topology"]["can_undo"]


def test_door_sized_gap_is_never_offered_a_fix():
    sess = process_plan(_plan(short_gap=int(5 * T), door_arc=True))
    res = session_result(sess)
    # A door-width gap is an opening, not a structural defect: no fix may close it.
    for i in res["topology"]["issues"]:
        if i["fix"]:
            for w in i["fix"]["after"]:
                assert not (abs(w["x1"] - 600) < T and min(w["y1"], w["y2"]) < 150 + T + 5 * T - 2)


def test_fix_api_roundtrip():
    png = _plan(short_gap=2 * T)
    d = client.post("/api/plans", files={"file": ("p.png", png, "image/png")}).json()
    issue = next(i for i in d["topology"]["issues"] if i["fixable"])
    r = client.post(f"/api/plans/{d['id']}/fixes", json={"key": issue["key"]})
    assert r.status_code == 200
    body = r.json()
    assert body["last_fix"]["resolved"] and body["geometry"]["corrected"]["stats"]["rooms"] == 2
    assert client.post(f"/api/plans/{d['id']}/fixes", json={"key": "nope"}).status_code == 409
    u = client.post(f"/api/plans/{d['id']}/fixes/undo")
    assert u.status_code == 200 and u.json()["geometry"]["corrected"]["stats"]["rooms"] == 1
    assert client.post(f"/api/plans/{d['id']}/fixes/undo").status_code == 409
