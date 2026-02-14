from __future__ import annotations

from pathlib import Path

from papercoach.models import AnnotationPlan


def write_low_confidence_report(plan: AnnotationPlan, out_html: Path, threshold: float = 0.45) -> None:
    rows: list[str] = []
    for page_idx, page in sorted(plan.pages.items()):
        for note in page.notes:
            if note.confidence <= threshold:
                rows.append(
                    "<tr>"
                    f"<td>{page_idx + 1}</td>"
                    f"<td>{note.title}</td>"
                    f"<td>{note.confidence:.2f}</td>"
                    f"<td>{', '.join(note.flags)}</td>"
                    "</tr>"
                )

    html = (
        "<html><head><title>PaperCoach Report</title></head><body>"
        "<h1>Low Confidence Notes</h1>"
        "<table border='1' cellspacing='0' cellpadding='6'>"
        "<tr><th>Page</th><th>Title</th><th>Confidence</th><th>Flags</th></tr>"
        + "".join(rows)
        + "</table></body></html>"
    )
    out_html.write_text(html, encoding="utf-8")
