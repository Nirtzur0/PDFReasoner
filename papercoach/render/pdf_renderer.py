"""PDF highlight rendering based on PyMuPDF annotation recipes.

Sources:
- https://pymupdf.readthedocs.io/en/latest/recipes-annotations.html
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path

import fitz

from papercoach.models import EquationExplanation, HighlightPlan, NoteSelection, QuadPoints
from papercoach.render.layout import AnchoredNote, MarginNote, place_notes
from papercoach.render.math_renderer import MathTextRenderer

_COLOR_MAP = {
    "contribution": (0.99, 0.93, 0.45),
    "method": (0.75, 0.9, 1.0),
    "result": (0.81, 0.95, 0.78),
    "setup": (0.92, 0.88, 1.0),
    "limitation": (1.0, 0.84, 0.84),
    "definition": (1.0, 0.9, 0.73),
}
_EQUATION_COLOR_MAP = {
    "objective": (0.74, 0.88, 1.0),
    "definition": (0.84, 0.93, 1.0),
    "transition": (0.78, 0.9, 1.0),
    "update": (0.78, 0.95, 0.9),
    "constraint": (1.0, 0.9, 0.78),
    "result": (0.83, 0.95, 0.83),
}


@dataclass(slots=True)
class RenderedPageNote:
    note: MarginNote
    quads: list[QuadPoints]


class PdfHighlightRenderer:
    def __init__(self) -> None:
        self._math_renderer = MathTextRenderer()

    def render(
        self,
        input_pdf: Path,
        output_pdf: Path,
        plan: HighlightPlan,
        margin_width: float,
        max_notes_per_page: int,
        max_equations_per_page: int,
    ) -> None:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open(input_pdf) as src, fitz.open() as out:
            for page_plan in plan.pages:
                src_page = src[page_plan.page_number - 1]
                notes = self._anchored_notes(page_plan, max_notes_per_page, max_equations_per_page)
                page_width = src_page.rect.width + margin_width if notes else src_page.rect.width
                page = out.new_page(width=page_width, height=src_page.rect.height)
                page.show_pdf_page(fitz.Rect(0, 0, src_page.rect.width, src_page.rect.height), src, src_page.number)
                if notes:
                    self._draw_margin_background(page, src_page.rect.width, src_page.rect.height, margin_width)
                for highlight in page_plan.highlights:
                    color = _COLOR_MAP.get(highlight.label, (0.99, 0.93, 0.45))
                    self._add_highlight_annotation(page, highlight.quads, color)
                for equation in page_plan.equations:
                    color = _EQUATION_COLOR_MAP.get(equation.role, (0.78, 0.9, 1.0))
                    self._add_highlight_annotation(page, equation.quads, color)
                if notes:
                    placements = place_notes(
                        notes,
                        page_height=src_page.rect.height,
                        margin_x0=src_page.rect.width + 18,
                        margin_x1=src_page.rect.width + margin_width - 18,
                        max_notes=max_notes_per_page + max_equations_per_page,
                    )
                    for placement in placements:
                        rendered_note = next(item for item in notes if item.note.note_id == placement.note.note_id)
                        self._draw_note(page, placement.note, placement.bbox, rendered_note.quads)
            out.save(output_pdf)

    def _draw_margin_background(self, page: fitz.Page, content_width: float, page_height: float, margin_width: float) -> None:
        x0 = content_width
        page.draw_rect(
            fitz.Rect(x0, 0, x0 + margin_width, page_height),
            color=(0.85, 0.87, 0.91),
            fill=(0.975, 0.978, 0.985),
            width=0.8,
        )
        page.draw_line((x0, 0), (x0, page_height), color=(0.82, 0.84, 0.88), width=0.8)

    def _add_highlight_annotation(
        self,
        page: fitz.Page,
        quads: list[QuadPoints],
        color: tuple[float, float, float],
    ) -> None:
        if not quads:
            return
        native_quads = [self._to_fitz_quad(quad) for quad in quads]
        annot = page.add_highlight_annot(native_quads)
        annot.set_colors(stroke=color)
        annot.update(opacity=0.35)

    def _draw_note(
        self,
        page: fitz.Page,
        note: MarginNote,
        bbox: tuple[float, float, float, float],
        quads: list[QuadPoints],
    ) -> None:
        rect = fitz.Rect(*bbox)
        title_lines = self._title_lines(note.title, rect.width - 20)
        title_bottom = rect.y0 + 10 + (title_lines * 14)
        body_top = title_bottom + 8
        page.draw_rect(
            rect,
            color=(0.78, 0.82, 0.88),
            fill=(1.0, 1.0, 1.0),
            width=0.9,
            radius=0.04,
        )
        page.insert_textbox(
            fitz.Rect(rect.x0 + 10, rect.y0 + 8, rect.x1 - 10, title_bottom),
            note.title,
            fontsize=9.8,
            fontname="helv",
            color=(0.14, 0.18, 0.28),
        )
        if note.equation_latex:
            body_top = self._draw_equation_latex(page, rect, body_top, note.equation_latex)
        if note.symbol_rows:
            body_top = self._draw_symbol_rows(page, rect, body_top, note.symbol_rows[:2])
        page.insert_textbox(
            fitz.Rect(rect.x0 + 10, body_top, rect.x1 - 10, rect.y1 - 10),
            note.body,
            fontsize=8.6,
            fontname="helv",
            color=(0.2, 0.22, 0.26),
            align=0,
        )

        if quads:
            anchor = quads[0]
            anchor_x = min(anchor.ur.x, anchor.lr.x)
            anchor_y = (anchor.ur.y + anchor.lr.y) / 2.0
            connector_y = min(rect.y1 - 18, body_top if body_top > rect.y0 + 18 else rect.y0 + 18)
            page.draw_line((rect.x0, connector_y), (anchor_x, anchor_y), color=(0.72, 0.74, 0.79), width=0.7)

    def _anchored_notes(self, page_plan, max_notes_per_page: int, max_equations_per_page: int) -> list[AnchoredNote]:
        anchored_notes: list[AnchoredNote] = []
        note_map = {note.highlight_id: note for note in page_plan.notes}
        for highlight in page_plan.highlights:
            note = note_map.get(highlight.highlight_id)
            if note is None or not highlight.quads:
                continue
            anchored_notes.append(
                AnchoredNote(
                    note=MarginNote(
                        note_id=note.note_id,
                        title=note.title,
                        body=note.body,
                        priority=1,
                    ),
                    anchor_y=self._anchor_y(highlight.quads),
                    quads=highlight.quads,
                )
            )
            if len([item for item in anchored_notes if item.note.priority == 1]) >= max_notes_per_page:
                break
        equation_map = {note.equation_id: note for note in page_plan.equation_notes}
        equation_count = 0
        for equation in page_plan.equations:
            note = equation_map.get(equation.equation_id)
            if note is None or not equation.quads:
                continue
            anchored_notes.append(
                AnchoredNote(
                    note=MarginNote(
                        note_id=note.equation_id,
                        title=note.title,
                        body=self._equation_body(note),
                        equation_latex=note.display_latex,
                        symbol_rows=list(note.symbol_map.items()),
                        priority=0 if equation.role in {"objective", "transition", "update"} else 1,
                    ),
                    anchor_y=self._anchor_y(equation.quads),
                    quads=equation.quads,
                )
            )
            equation_count += 1
            if equation_count >= max_equations_per_page:
                break
        return anchored_notes

    def _equation_body(self, note: EquationExplanation) -> str:
        parts = [note.body]
        if note.intuition and len(note.body) < 150:
            parts.append(note.intuition)
        return " ".join(part for part in parts if part)[:280].strip()

    def _draw_equation_latex(self, page: fitz.Page, rect: fitz.Rect, top: float, equation_latex: str) -> float:
        rendered = self._math_renderer.render(equation_latex, font_size=12.2)
        if rendered is None:
            return top
        available_width = rect.width - 20
        scale = min(1.0, available_width / max(rendered.width, 1.0))
        draw_width = rendered.width * scale
        draw_height = rendered.height * scale
        x0 = rect.x0 + 10 + max(0.0, (available_width - draw_width) / 2.0)
        image_rect = fitz.Rect(x0, top, x0 + draw_width, top + draw_height)
        page.insert_image(image_rect, stream=rendered.png_bytes, keep_proportion=True, overlay=True)
        return image_rect.y1 + 6

    def _draw_symbol_rows(
        self,
        page: fitz.Page,
        rect: fitz.Rect,
        top: float,
        symbol_rows: list[tuple[str, str]],
    ) -> float:
        symbol_width = min(74.0, max(56.0, rect.width * 0.28))
        for symbol_latex, meaning in symbol_rows:
            rendered = self._math_renderer.render(symbol_latex, font_size=10.0)
            row_height = 16.0
            if rendered is not None:
                scale = min(1.0, symbol_width / max(rendered.width, 1.0))
                draw_width = rendered.width * scale
                draw_height = rendered.height * scale
                row_height = max(row_height, draw_height)
                image_rect = fitz.Rect(rect.x0 + 10, top, rect.x0 + 10 + draw_width, top + draw_height)
                page.insert_image(image_rect, stream=rendered.png_bytes, keep_proportion=True, overlay=True)
            else:
                page.insert_textbox(
                    fitz.Rect(rect.x0 + 10, top, rect.x0 + 10 + symbol_width, top + row_height),
                    symbol_latex,
                    fontsize=8.7,
                    fontname="cour",
                    color=(0.16, 0.19, 0.28),
                )
            page.insert_textbox(
                fitz.Rect(rect.x0 + 10 + symbol_width + 8, top - 1, rect.x1 - 10, top + row_height + 3),
                meaning,
                fontsize=8.1,
                fontname="helv",
                color=(0.26, 0.28, 0.32),
            )
            top += row_height + 4
        return top + 2

    def _title_lines(self, title: str, width: float) -> int:
        chars_per_line = max(16, int(width / 7.5))
        return max(1, ceil(len(title) / chars_per_line))

    def _anchor_y(self, quads: list[QuadPoints]) -> float:
        quad = quads[0]
        return (quad.ur.y + quad.lr.y) / 2.0

    def _to_fitz_quad(self, quad: QuadPoints) -> fitz.Quad:
        return fitz.Quad(
            (
                fitz.Point(quad.ul.x, quad.ul.y),
                fitz.Point(quad.ur.x, quad.ur.y),
                fitz.Point(quad.ll.x, quad.ll.y),
                fitz.Point(quad.lr.x, quad.lr.y),
            )
        )
