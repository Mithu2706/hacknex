# ArchNext — *Every Line Becomes a Space.*

HackNex 2026 · HNX26EPS06 · Mode A — Floor Plan to 3D Reconstruction.

ArchNext turns an uploaded 2D floor plan (PNG / JPG / WebP) into a scaled, explorable 3D building:

```
upload → preprocessing → wall / room / door / window detection → vectorisation
       → TopologyGuard → ScaleLock → procedural 3D (Three.js) → 3D Studio → GLB export
```

All geometry comes from the uploaded image. There is no sample building and no hard-coded geometry.

---

## Windows quick start

Requirements: **Python 3.10** (the `py` launcher) and **Node.js 18+**.

```bat
cd C:\Users\Dell\OneDrive\Desktop\ArchNext
setup_windows.bat
```

Then run the two services in two terminals:

```bat
start_backend.bat      :: http://127.0.0.1:8000  (API)
start_frontend.bat     :: http://localhost:5173   (open this in the browser)
```

Or run a single process that serves the built interface and the API together:

```bat
start_demo.bat         :: builds the UI and opens http://127.0.0.1:8000
```

Manual equivalent:

```bat
cd backend
py -3.10 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

:: second terminal
cd frontend
npm install
npm run dev
```

The first upload takes a few seconds longer while the text-recognition models load.

---

## Which parser is used

**The OpenCV structural parser in `backend/app/pipeline/` is used.** It is a rule-based computer-vision
parser, not a pretrained AI model.

The candidate pretrained model (`Yytsi/floorplan-to-3d-walls`, a ResNet-34 UNet trained on CubiCasa5K)
was evaluated but **not integrated**: the build environment's network policy blocked downloads from
Hugging Face (HTTP 403), so its weights, preprocessing and inference could not be verified. Its
upstream pipeline also expects CubiCasa-style SVG input rasterised with Cairo, not arbitrary raster plans. The
parser keeps both geometry versions behind one interface, so a verified model can replace the detection step
later. All evaluated configurations use the same OpenCV parser. The Hugging Face model is **not** active.

Text recognition (room names and dimension labels) uses **RapidOCR** (`rapidocr-onnxruntime`), which runs
on CPU and needs no system install.

### How the parser works

1. **Preprocessing:** EXIF orientation, alpha flattening, resampling to a 1100–2000 px working size,
   illumination compensation for photographed plans, and a dark-ink threshold capped so that grey fills
   and hatching are not treated as ink. Speckle removal.
2. **Wall thickness estimation:** a distance-transform ridge histogram separates thin strokes (text,
   furniture, dimension lines, door swings) from wall-thickness strokes.
3. **Wall mask:** morphological opening at the wall thickness removes everything thinner than a wall.
   Compact blobs such as arrows and bold glyphs, and anything inside OCR text boxes, are discarded.
4. **Vectorisation:** run-length band extraction gives horizontal and vertical wall rectangles. Residual
   components become oblique walls (minimum-area rectangles). Massive blocks such as chimney breasts are kept.
5. **Openings:** rays cast from wall ends find gaps. Each gap is classified from the original ink:
   door-swing arcs (contrast-tested against clutter) mean a **door**; glazing lines across the gap mean a
   **window**; otherwise it is a plain **opening**. Wide gaps and gaps next to an existing junction need
   positive evidence.
6. **Rooms:** walls and openings are rasterised and the remaining free space is labelled. Regions
   connected to the image border are exterior. Walls next to exterior space are marked as exterior walls.
   OCR text inside a room gives its name and type.

---

## Feature 1 — TopologyGuard

TopologyGuard runs on the extracted vector walls. It keeps both the **original** (parser) geometry and
the **corrected** geometry, so the difference can be measured.

| Check | Action |
|---|---|
| Duplicate wall segments | merged (auto) |
| Stray wall fragments | removed if tiny *and* isolated (auto) |
| Broken wall lines (gap < 1.1 × wall thickness) | closed (auto); a door can never be that narrow |
| Junction gaps (wall stops ≤ 1.5 × thickness short) | extended to the junction (auto) |
| Junction overshoots | trimmed (auto) |
| Ambiguous gaps (between a break and a door) | left open, **flagged for review** |
| Suspicious / oblique intersections | flagged for review |
| Disconnected wall ends | flagged for review |
| Door / window placement | removed if overlapping another wall; windows on interior walls flagged |
| Room enclosure | open boundaries that leak a room to the outside are flagged |

Door-sized gaps are never closed automatically.

### Fix buttons (first part of Fix2Build)

After the automatic pass, the remaining issues are re-detected on the **current** geometry and listed in
**Analysis → TopologyGuard → Needs attention**. Clicking an issue highlights it on the blueprint.

| Remaining issue | Offered action |
|---|---|
| Narrow gap in a straight wall (1.1–1.9 × wall thickness) | **Close gap** (merges the two segments) |
| Wall stopping short of a junction (up to 1.9 × thickness) | **Connect walls** (extends the wall to the junction) |
| Two walls almost meeting at a corner | **Align junction** (both ends moved to a clean corner, each by ≤ 2 × thickness) |
| Overlapping parallel segments of similar thickness | **Remove duplicate** |
| Anything else (free wall ends, oblique crossings, uncertain openings, gaps showing door/window markings) | **Manual review required**, no button |

A fix is offered only if it is local, the gap shows no door-swing or glazing marks, the new geometry does
not cover a detected door or window, and the wall end is actually connected afterwards. **Fix** shows a
preview (red dashed = current, green = after); **Apply** changes the stored wall geometry. Openings,
rooms, room dimensions, ScaleLock label matching, all checks and the 3D model / GLB are then recomputed.
**Undo** restores the previous geometry exactly (up to 20 steps). "All structural checks pass" is only
shown when the re-run checks find nothing. User fixes are never counted in the automatic accuracy scores.

## Feature 2 — ScaleLock

* **Automatic:** OCR reads dimension text. The parser handles metric (`3.45 x 4.10 m`, `2400 mm`, unitless
  `322X347`) and imperial (`10'1" x 11'1"`, `14'6"`) values. Room labels are compared with the rectangular
  room they sit in, and both sides must give the same scale. Stand-alone values are matched to the
  dimension line next to them. Unitless values are tested as m, cm and mm.
* **Consensus:** the scale with the most agreeing measurements (within 8 %) wins, and the median of those
  is used. Inconsistent measurements are **rejected** with a reason; they are never averaged in. One value
  that nothing confirms is not trusted, except a room label whose two dimensions agree with each other
  (low confidence).
* **Hold-out check:** each accepted label is predicted from the others and the error is shown in Validation.
* **Manual fallback:** mark two points on the blueprint and enter the distance in m, cm, mm, ft or in.
* **Estimated:** if neither is available, the scale is estimated from a typical door width (0.85 m) or
  wall thickness, and shown as *Estimated — not calibrated*.

Wall height (2.7 m), door height (2.1 m) and window sill / head (0.9 / 2.1 m) are **assumptions** and are
labelled as such. Wall thickness comes from the plan.

---

## The four views

* **Upload** — drag and drop or browse, preview, *Generate 3D*. Shows processing status without
  invented percentages, and errors with a retry option.
* **Analysis** — blueprint overlay (walls, rooms, doors and windows, issues, dimension labels), a switch
  between *Detected* and *TopologyGuard corrected*, the TopologyGuard panel, and the ScaleLock panel with
  manual calibration.
* **3D Studio** — orbit, pan and zoom; perspective, top view, and a first-person **walkthrough** (WASD,
  walls block movement); reset camera; room labels; wall-height control; **Export GLB**.
* **Validation** — (A) four overview cards (room detection, structural connectivity, dimension error,
  room overlap), each labelled with its source; (B) before-vs-after charts; (C) the four-way ablation with
  a metric selector and detailed table; (D) scale verification (written vs predicted, calibration method,
  warnings); (E) advanced sections: structural checks, room schedule, annotation upload, precision/recall/
  IoU/F1 details, full benchmark tables. A switch selects **This plan** or **Synthetic benchmark**; without an
  annotation, plan accuracy shows *Not evaluated*, never a borrowed number.

---

## Evaluation

`backend/eval/synth.py` generates floor plans with exact ground truth: rooms, doors, windows and scale. It
draws them in a conventional style with wall breaks, junction gaps and speckle noise injected into the
raster.

### Four-way ablation

`python -m eval.run_benchmark 20 --verify` runs the full pipeline **independently** for each
configuration on the same 20 plans (seeds 100–119) with the same parser and metric definitions. Then it
runs the whole study again and checks that the results are identical.

| Configuration | TopologyGuard | ScaleLock |
|---|---|---|
| Baseline | off | off (estimated scale) |
| TopologyGuard only | on | off (estimated scale) |
| ScaleLock only | off | on |
| Full ArchNext | on | on |

**Synthetic benchmark — 20 generated floor plans. Results do not establish real-world accuracy.**
From `backend/eval/results/benchmark.md` (re-run: identical):

| Metric | Baseline | TopologyGuard only | ScaleLock only | Full ArchNext |
|---|---|---|---|---|
| Room recall | 0.337 | 0.963 | 0.337 | 0.963 |
| Room precision | 0.663 | 0.992 | 0.663 | 0.992 |
| Room IoU (all GT rooms) | 0.288 | 0.940 | 0.288 | 0.940 |
| Room-type accuracy | 0.877 | 0.976 | 0.877 | 0.976 |
| Dimension error | 15.5 % | 4.7 % | 13.7 % | 1.1 % |
| Scale error | 3.2 % | 3.3 % | 1.4 % | 0.7 % |
| Wall connectivity | 0.901 | 0.991 | 0.901 | 0.991 |
| Door F1 | 0.992 | 0.992 | 0.992 | 0.992 |
| Window F1 | 0.989 | 0.989 | 0.989 | 0.989 |

What the ablation shows:
* **TopologyGuard** drives room recovery: recall goes from 0.34 to 0.96, IoU from 0.29 to 0.94.
* **ScaleLock** drives metric accuracy, but it **depends on TopologyGuard**. Alone it reaches 1.4 % scale
  error yet 13.7 % dimension error, because rooms are still merged. Combined it gives 1.1 % dimension error.
* Neither changes door/window detection. Both use the same opening classifier, which is part of the parser.

The first run of this ablation exposed a ScaleLock weakness. With TopologyGuard off, several room labels
landed inside one merged space and "agreed" on a wrong scale (3 plans with 40–67 % scale error; mean 9.6 %).
ScaleLock now rejects labels that share one detected space. The pre-fix table is kept in
`backend/eval/results/ablation_before_merged_label_rule.md`.

In the app, uploading an annotation for the current plan re-runs the same four configurations on that plan.
No real-world annotated test set is included, so real-world accuracy is reported as **not evaluated**.

Real plans tested during development (third-party images used only for local testing, not included in the
repository):

| Plan | Result |
|---|---|
| CubiCasa-style apartment (imperial labels) | 8 rooms; auto-calibrated from 3 labels; hold-out error 0.2–0.9 % |
| Scanned Israeli apartment (cm labels, Hebrew text) | 15 rooms; auto-calibrated from 4 agreeing cm labels (hold-out error 0.5–5.8 %); 9 inconsistent or unmatched labels rejected; open kitchen/living area joins the stairwell and is treated as exterior |
| UK terraced-house plan (no dimensions) | rooms 4 → 8 after TopologyGuard; scale estimated; manual calibration available |
| Australian marketing plan (grey interior walls) | **fails to form rooms**: only the thick exterior walls are detected |

`samples/` has two generated plans with annotation files. Upload `generated_plan_7.png`, then load
`generated_plan_7.json` in **Validation → Ground-truth evaluation** to see the metrics live.

### Tests run

* `cd backend && python -m pytest -q`: **9 tests**:
  * dimension parsing
  * TopologyGuard closes breaks but keeps openings
  * end-to-end reconstruction with auto scale under 3 % error
  * different plans give different geometry
  * the API: upload, manual calibration (labelled *manual*, dimensions double), unrealistic-reference
    warnings, reset, four-way annotation evaluation
  * invalid uploads
  * **fixes**: Connect changes the real wall coordinates and splits the merged room, the issue
    disappears, Undo restores identical geometry, door-width gaps are never offered a fix, and the
    fix/undo API round-trips
* Browser end-to-end (headless Chromium):
  * upload → Analysis → Fix preview → Apply → 3D Studio → GLB export
  * the exported GLB changes (the moved walls and the recomputed floors), and after Undo it is node-for-node
    identical to the original
  * Validation in both source modes, with annotation upload
  * no console errors
* Exported GLBs, including one exported after applying a fix, pass the Khronos glTF Validator with
  0 errors and 0 warnings.
* `npm run build` succeeds.

---

## Known limitations

* Walls must be drawn as dark, solid (filled) strokes. Plans that draw walls only as thin double outlines,
  or that draw interior walls in light grey, are only partly reconstructed (often exterior walls only).
* Curved walls are not reconstructed. Oblique walls are supported when they are drawn solid.
* Door vs. window classification depends on door swings and glazing lines. Sliding doors usually come
  out as uncertain openings, which are flagged. Glazing-like gaps on purely interior walls are no longer
  called windows; they become uncertain openings instead.
* Open-plan areas and spaces that open to stairwells are merged or treated as exterior.
* OCR reads Latin text and digits. Other scripts (for example Hebrew room names) are not used for names,
  but their numeric dimension labels are.
* Single-floor plans only. Photographed plans with perspective distortion are not rectified.
* Sessions are kept in memory: restarting the backend clears uploaded plans and fixes.

## Fix2Build status

**Implemented:** issue-based fixes with preview, apply and undo (above). **Not implemented:** free-form
editing of wall endpoints, room polygons and opening positions (no CAD editor).

## Project layout

```
backend/
  app/main.py              FastAPI endpoints (upload, image, calibration, evaluation, benchmark)
  app/pipeline/            preprocess, walls, structure (openings), rooms, topology (TopologyGuard),
                           scalelock, measure (dimension parsing), ocr, run (orchestration)
  app/pipeline/fixes.py    remaining-issue detection, safe fix proposals, apply
  app/evaluation.py        ground-truth metrics and the four ablation configurations
  eval/synth.py            generated plans with exact ground truth
  eval/run_benchmark.py    four-way ablation -> eval/results/
  tests/                   pytest suite
frontend/
  src/views/               Upload, Analysis, 3D Studio, Validation
  src/components/          blueprint overlay, TopologyGuard / ScaleLock panels, walkthrough
  src/lib/buildModel.js    procedural Three.js building + GLB export source
samples/                   generated plans + annotation files
```
