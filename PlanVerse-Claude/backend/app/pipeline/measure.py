"""Parsing of dimension strings found on floor plans (metric and imperial)."""
from __future__ import annotations

import re
from dataclasses import dataclass

FT = 0.3048
IN = 0.0254

_QUOTE_FIX = str.maketrans({"’": "'", "‘": "'", "′": "'", "´": "'", "`": "'", "”": '"', "“": '"',
                            "″": '"', "*": '"', ",": ".", "×": "x", "X": "x", "Х": "x", "х": "x"})

_FEET = re.compile(r"^(\d{1,3})\s*'\s*-?\s*(?:(\d{1,2}(?:\.\d+)?)\s*(?:\"|''|in)?)?$")
_INCH_ONLY = re.compile(r"^(\d{1,3}(?:\.\d+)?)\s*(?:\"|in)$")
_METRIC = re.compile(r"^(\d{1,5}(?:\.\d{1,3})?)\s*(mm|cm|m)?$")
_PAIR_SPLIT = re.compile(r"\s*x\s*")


@dataclass
class Length:
    value: float           # numeric value as written
    unit: str | None       # 'ft', 'm', 'cm', 'mm' or None when no unit was written
    meters: float | None   # resolved meters if unit is known

    def candidates(self, context: str) -> list[tuple[str, float]]:
        """Possible (unit, meters) interpretations for this length."""
        if self.meters is not None:
            return [(self.unit or "", self.meters)]
        v = self.value
        out = []
        lo, hi = (0.8, 20.0) if context == "room" else (1.0, 120.0)
        for unit, f in (("m", 1.0), ("cm", 0.01), ("mm", 0.001)):
            m = v * f
            if lo <= m <= hi:
                # A bare integer is unlikely to be metres when it is large; decimals rarely mm.
                if unit == "m" and v >= 30:
                    continue
                if unit == "mm" and "." in f"{v}" and v != int(v):
                    continue
                out.append((unit, m))
        return out


def _clean(text: str) -> str:
    t = text.translate(_QUOTE_FIX).strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = t.replace("''", '"')
    return t


def parse_length(token: str, default_unit: str | None = None) -> Length | None:
    t = token.strip().rstrip(".")
    if not t:
        return None
    m = _FEET.match(t)
    if m:
        ft = float(m.group(1))
        inch = float(m.group(2)) if m.group(2) else 0.0
        if inch >= 12:
            return None
        return Length(ft + inch / 12, "ft", ft * FT + inch * IN)
    m = _INCH_ONLY.match(t)
    if m:
        v = float(m.group(1))
        return Length(v, "in", v * IN)
    m = _METRIC.match(t)
    if m:
        v = float(m.group(1))
        unit = m.group(2) or default_unit
        if v <= 0:
            return None
        if unit:
            f = {"m": 1.0, "cm": 0.01, "mm": 0.001}[unit]
            return Length(v, unit, v * f)
        return Length(v, None, None)
    return None


def _trailing_unit(text: str) -> tuple[str, str | None]:
    m = re.search(r"\s*(mm|cm|m)\.?$", text)
    if m and re.search(r"\d\s*(mm|cm|m)\.?$", text):
        return text[: m.start()], m.group(1)
    return text, None


def parse_dimension(text: str) -> dict | None:
    """Parse a dimension label.

    Returns {'kind': 'pair'|'single', 'lengths': [Length, ...]} or None when the text is not a
    measurement.
    """
    t = _clean(text)
    if not re.search(r"\d", t):
        return None
    if re.search(r"[a-wyz]{3,}", t.replace("mm", "").replace("cm", "")):
        return None  # words, not a dimension
    t = t.replace("m2", "").strip()
    body, unit = _trailing_unit(t)
    parts = [p for p in _PAIR_SPLIT.split(body) if p]
    if len(parts) == 2:
        a = parse_length(parts[0], unit)
        b = parse_length(parts[1], unit)
        # Imperial: OCR often drops the trailing inch mark, e.g. 18'1 -> handled by _FEET.
        if a and b:
            units = {a.unit, b.unit}
            if "ft" in units and units != {"ft"}:
                return None  # mixed feet/other units: almost always an OCR misread
            if None in units and units != {None}:
                return None
            return {"kind": "pair", "lengths": [a, b]}
        return None
    if len(parts) == 1:
        a = parse_length(parts[0], unit)
        if a is None:
            return None
        # A lone bare number is only a dimension if it is plausibly one (avoid "18", "2", ...).
        if a.unit is None and (a.value < 100 and "." not in parts[0]):
            return None
        return {"kind": "single", "lengths": [a]}
    return None
