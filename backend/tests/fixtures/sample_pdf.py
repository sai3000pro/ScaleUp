"""Generate a small, structured PDF in memory.

Structured on purpose: real headings and numbered sections, so the same helper
exercises heading detection and chunking in M4 rather than only the upload path.
No binary fixture in git, and the content is visible in the diff.
"""

from __future__ import annotations

import pymupdf

SECTIONS: list[tuple[str, str]] = [
    (
        "1  Vectors",
        "A vector is an ordered list of numbers. Vectors add componentwise and scale by a "
        "real number. The zero vector is the additive identity. Geometrically a vector in "
        "the plane is an arrow with a length and a direction.",
    ),
    (
        "1.1  The Dot Product",
        "The dot product of two vectors multiplies matching components and sums the results. "
        "It returns a single number rather than a vector. The dot product is zero exactly "
        "when the two vectors are perpendicular, which makes it the basic test for "
        "orthogonality.",
    ),
    (
        "2  Matrices",
        "A matrix is a rectangular array of numbers. Matrix addition is componentwise. "
        "Multiplying a matrix by a scalar multiplies every entry.",
    ),
    (
        "2.1  Matrix Multiplication",
        "To multiply two matrices, take the dot product of row i of the first matrix with "
        "column j of the second to produce the entry in row i, column j of the result. "
        "Matrix multiplication is associative but not commutative. It requires the inner "
        "dimensions to agree.",
    ),
    (
        "3  Linear Independence",
        "A set of vectors is linearly independent when no vector in the set can be written "
        "as a combination of the others. Independence is what makes a spanning set a basis, "
        "and it is checked by solving a homogeneous system.",
    ),
]


def build_sample_pdf(title: str = "Linear Algebra, Abridged") -> bytes:
    """Return the bytes of a short multi-section PDF."""
    document = pymupdf.open()

    page = document.new_page()
    page.insert_text((72, 90), title, fontsize=22, fontname="helv")
    cursor = 140.0
    for heading, body in SECTIONS:
        if cursor > 660:
            page = document.new_page()
            cursor = 90.0
        page.insert_text((72, cursor), heading, fontsize=15, fontname="hebo")
        cursor += 24
        wrapped = pymupdf.Rect(72, cursor, 523, cursor + 130)
        page.insert_textbox(wrapped, body, fontsize=11, fontname="helv")
        cursor += 150

    payload: bytes = document.tobytes()
    document.close()
    return payload
