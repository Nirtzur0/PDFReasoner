from __future__ import annotations

from pathlib import Path

import fitz
import pytest


@pytest.fixture()
def sample_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "sample.pdf"
    doc = fitz.open()

    p1 = doc.new_page()
    p1.insert_text((50, 60), "Abstract", fontsize=14)
    p1.insert_text((50, 90), "This paper studies optimization methods in high dimensions.", fontsize=10)
    p1.insert_text((50, 120), "1 Introduction", fontsize=13)
    p1.insert_text((50, 150), "Definition 1. Let x be a vector in R^d where x denotes parameters.", fontsize=10)
    p1.insert_text((50, 180), "Theorem 1. The objective converges under mild assumptions.", fontsize=10)
    p1.insert_text((50, 210), "Proof. Clearly, it follows from convexity.", fontsize=10)
    p1.insert_text((50, 240), "As in [1], we apply gradient descent.", fontsize=10)
    p1.insert_text((50, 270), "L = ||x||^2 + lambda * y", fontsize=10)

    p2 = doc.new_page()
    p2.insert_text((50, 60), "References", fontsize=13)
    p2.insert_text((50, 90), "[1] Smith, J. (2019). Gradient Methods for Large Models.", fontsize=10)

    doc.save(pdf)
    doc.close()
    return pdf
