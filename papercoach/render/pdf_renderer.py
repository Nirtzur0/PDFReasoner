from __future__ import annotations

from pathlib import Path

import fitz

from papercoach.models import AnnotationPlan, MarginNote
from papercoach.render.layout import place_notes


def _draw_note(page: fitz.Page, note: MarginNote, note_bbox: list[float], anchor_bbox: list[float]) -> None:
    rect = fitz.Rect(*note_bbox)
    page.draw_rect(rect, color=(0.2, 0.2, 0.2), fill=(0.97, 0.97, 0.97), width=0.7)
    text = note.title.strip() + "\n" + note.body.strip()
    page.insert_textbox(
        rect + (4, 4, -4, -4),
        text,
        fontsize=8,
        fontname="helv",
        color=(0.1, 0.1, 0.1),
        align=0,
    )

    anchor_center = ((anchor_bbox[0] + anchor_bbox[2]) / 2, (anchor_bbox[1] + anchor_bbox[3]) / 2)
    callout_start = (rect.x0, (rect.y0 + rect.y1) / 2)
    page.draw_line(callout_start, anchor_center, color=(0.5, 0.2, 0.2), width=0.6)


def _draw_highlight(page: fitz.Page, bbox: list[float], tag: str) -> None:
    color_map = {
        "theorem_like": (1.0, 1.0, 0.4),
        "proof": (0.8, 1.0, 0.8),
        "equation": (0.8, 0.9, 1.0),
        "section_heading": (1.0, 0.9, 0.7),
        "focus": (1.0, 0.96, 0.6),
    }
    fill = color_map.get(tag, (1.0, 0.95, 0.75))
    page.draw_rect(fitz.Rect(*bbox), color=(0.6, 0.6, 0.1), fill=fill, width=0.6, overlay=True)


def _insert_mindmap_page(doc: fitz.Document, mindmap_path: Path, position: str) -> None:
    if not mindmap_path.exists():
        return
    if position == "cover":
        page = doc.new_page(pno=0)
    else:
        page = doc.new_page()
    page.insert_text((40, 40), "Mind Map", fontsize=18, fontname="helv")
    img_rect = fitz.Rect(40, 70, page.rect.width - 40, page.rect.height - 40)
    try:
        page.insert_image(img_rect, filename=str(mindmap_path), keep_proportion=False)
    except Exception:
        page.insert_text((40, 90), "Mind map image unavailable.", fontsize=10, fontname="helv")


def render_pdf(
    input_pdf: Path,
    output_pdf: Path,
    plan: AnnotationPlan,
    margin_width: float,
    max_notes_per_page: int,
    mindmap_position: str,
) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(input_pdf) as src, fitz.open() as out:
        overflow_notes: list[MarginNote] = []
        for page_idx, src_page in enumerate(src):
            src_rect = src_page.rect
            out_page = out.new_page(width=src_rect.width + margin_width, height=src_rect.height)
            left_rect = fitz.Rect(0, 0, src_rect.width, src_rect.height)
            out_page.show_pdf_page(left_rect, src, page_idx)

            page_plan = plan.pages.get(page_idx)
            if not page_plan:
                continue

            for hl in page_plan.highlights:
                _draw_highlight(out_page, hl.bbox, hl.tag)

            notes = page_plan.notes
            placements, overflow = place_notes(
                notes,
                page_height=src_rect.height,
                margin_x0=src_rect.width + 8,
                margin_x1=src_rect.width + margin_width - 8,
                max_notes=max_notes_per_page,
            )
            overflow_notes.extend(overflow)
            for place in placements:
                place.note.note_bbox = place.bbox
                _draw_note(out_page, place.note, place.bbox, place.note.anchor_bbox)

        if overflow_notes:
            page = out.new_page()
            page.insert_text((40, 40), "Overflow Notes", fontsize=18, fontname="helv")
            y = 70
            for note in overflow_notes:
                page.insert_text((40, y), f"- p.{note.page + 1}: {note.title}", fontsize=9, fontname="helv")
                y += 13
                if y > page.rect.height - 40:
                    page = out.new_page()
                    y = 40

        mindmap_path = Path(plan.mindmaps[0].path) if plan.mindmaps else None
        if mindmap_path:
            _insert_mindmap_page(out, mindmap_path, mindmap_position)

        out.save(output_pdf)
