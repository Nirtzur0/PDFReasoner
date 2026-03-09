"""Math snippet rendering for equation notes.

Sources:
- https://matplotlib.org/stable/users/explain/text/mathtext.html
- https://pymupdf.readthedocs.io/en/latest/page.html#Page.insert_image
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import fitz
from matplotlib import mathtext
from matplotlib.font_manager import FontProperties


@dataclass(slots=True)
class RenderedMath:
    png_bytes: bytes
    width: float
    height: float


class MathTextRenderer:
    def __init__(self, dpi: int = 220) -> None:
        self._dpi = dpi
        self._cache: dict[tuple[str, float, tuple[float, float, float]], RenderedMath] = {}

    def render(
        self,
        expression: str | None,
        font_size: float,
        color: tuple[float, float, float] = (0.16, 0.19, 0.28),
    ) -> RenderedMath | None:
        normalized = self._normalize(expression)
        if not normalized:
            return None
        cache_key = (normalized, round(font_size, 2), color)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        buffer = BytesIO()
        try:
            mathtext.math_to_image(
                f"${normalized}$",
                buffer,
                prop=FontProperties(size=font_size),
                dpi=self._dpi,
                format="png",
                color=color,
            )
            png_bytes = buffer.getvalue()
            pixmap = fitz.Pixmap(png_bytes)
        except Exception:
            return None

        rendered = RenderedMath(
            png_bytes=png_bytes,
            width=(pixmap.width * 72.0) / self._dpi,
            height=(pixmap.height * 72.0) / self._dpi,
        )
        self._cache[cache_key] = rendered
        return rendered

    def _normalize(self, expression: str | None) -> str:
        if expression is None:
            return ""
        cleaned = expression.strip()
        if not cleaned:
            return ""
        if cleaned.startswith("$") and cleaned.endswith("$") and len(cleaned) >= 2:
            cleaned = cleaned[1:-1].strip()
        return cleaned
