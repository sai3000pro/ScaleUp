"""A green job over a course that gained nothing is the worst failure mode.

Every status the user can see says it worked; only drilling reveals the tree is
site furniture. The guard therefore measures prose, not characters -- a
character count passed the case that motivated it.
"""

from __future__ import annotations

import pytest

from app.services.ingest_pipeline import EmptyDocumentError, _require_readable_text

# Reconstructed from the real failure: ocw.mit.edu renders its content with
# JavaScript, so the server returns a shell whose nav bar extracts to ~700
# characters of one- and two-word labels.
NAV_SHELL = [
    "Course Description Instructor Departments Topics Mathematics Linear Algebra "
    "Course Info Learning Resource Types Lecture Videos Problem Sets Exams "
    "Assignments Syllabus Calendar Readings Download Course Menu Search "
    "Give Now About OCW Help & FAQs Contact Us Advanced Search Browse Course "
    "Collections Educator Resources New Courses Most Visited Courses "
    "Translated Courses Supplemental Resources Archived Courses"
]

REAL_PROSE = [
    "This course covers matrix theory and linear algebra, emphasizing topics "
    "useful in other disciplines. Linear algebra is a branch of mathematics "
    "that studies systems of linear equations and the properties of matrices. "
    "The concepts of linear algebra are extremely useful in physics, economics "
    "and social sciences, natural sciences, and engineering."
]


def test_a_javascript_shell_is_refused_even_though_it_has_characters() -> None:
    """The case a character floor let through."""
    assert sum(len(t) for t in NAV_SHELL) > 400, "fixture must clear a naive character floor"

    with pytest.raises(EmptyDocumentError, match="JavaScript"):
        _require_readable_text(NAV_SHELL, "ocw-linear-algebra.html", "html")


def test_real_prose_passes() -> None:
    _require_readable_text(REAL_PROSE, "article.html", "html")


def test_an_empty_document_is_refused() -> None:
    with pytest.raises(EmptyDocumentError):
        _require_readable_text(["", "   ", "\n"], "blank.pdf", "pdf")


def test_the_hint_names_the_actual_remedy_per_format() -> None:
    """A PDF cannot be fixed by enabling JavaScript, and vice versa."""
    with pytest.raises(EmptyDocumentError, match="OCR"):
        _require_readable_text([""], "scan.pdf", "pdf")

    with pytest.raises(EmptyDocumentError, match="JavaScript"):
        _require_readable_text([""], "spa.html", "html")


def test_a_maths_heavy_textbook_page_still_passes() -> None:
    """The guard must not reject the material this product exists to ingest.

    82% of extracted lines in the CO 250 text layer are 1-4 token fragments of
    flattened notation. That is what a real optimisation textbook looks like,
    and it is content -- the guard is looking for navigation, not for symbols.
    Verbatim from page 30.
    """
    page = [
        "Notation let B be a subset of column indices, then AB is a columns "
        "sub-matrix of A indexed by set B. Ai denotes the columns i of A. "
        "Definition Let B be a subset of column indices, B is a basis if AB is "
        "invertible (non-sigular). Remark Some properties of basis: Max number "
        "of independent columns = Max number of independent rows. B is a basis "
        "if and only if B is a maximal set of independent columns of A."
    ]
    _require_readable_text(page, "CO250_textbook.pdf", "pdf")
