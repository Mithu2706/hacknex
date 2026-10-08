"""Text recognition used for room labels and ScaleLock dimension strings."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)
_engine = None
_engine_error: str | None = None
_lock = threading.Lock()


@dataclass
class TextItem:
    text: str
    score: float
    x: float
    y: float
    w: float
    h: float
    vertical: bool

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def to_dict(self) -> dict:
        return {"text": self.text, "score": round(self.score, 3),
                "bbox": [round(self.x, 1), round(self.y, 1), round(self.w, 1), round(self.h, 1)],
                "vertical": self.vertical}


def _get_engine():
    global _engine, _engine_error
    with _lock:
        if _engine is None and _engine_error is None:
            try:
                from rapidocr_onnxruntime import RapidOCR  # type: ignore
                _engine = RapidOCR()
            except Exception as exc:  # noqa: BLE001
                _engine_error = str(exc)
                log.warning("OCR engine unavailable: %s", exc)
        return _engine


def ocr_available() -> bool:
    return _get_engine() is not None


def read_text(rgb: np.ndarray, min_score: float = 0.45) -> tuple[list[TextItem], bool]:
    """Return recognised text items and whether OCR was available."""
    engine = _get_engine()
    if engine is None:
        return [], False
    try:
        result, _ = engine(rgb)
    except Exception as exc:  # noqa: BLE001
        log.warning("OCR failed: %s", exc)
        return [], False
    items: list[TextItem] = []
    for box, text, score in result or []:
        score = float(score)
        text = str(text).strip()
        if not text or score < min_score:
            continue
        pts = np.array(box, dtype=float)
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        w, h = x1 - x0, y1 - y0
        items.append(TextItem(text, score, float(x0), float(y0), float(w), float(h),
                              vertical=bool(h > 1.4 * w and len(text) > 1)))
    return items, True
