"""Generate a small, realistically-dirty HTML page in memory.

Mirrors `sample_pdf.py`: no binary fixture in git, and the content is visible in
the diff. "Realistically dirty" is the point -- a clean `<h2>`/`<p>` document
would pass a parser that does no boilerplate removal at all, so the page carries
the furniture a real article carries: a site chrome header with navigation, a
newsletter interstitial in the middle of the prose, a related-links block, a
cookie banner, an inline script, and a footer.

Every one of those blocks contains a distinctive marker string, and the parser
tests assert those strings survive in **no** block, **no** page text, and **no**
chunk. A boilerplate rule that half-works is worse than none: it leaves the
learner a node called "Subscribe" and a drill question about a cookie policy.
"""

from __future__ import annotations

# Deliberately SHOUTED and unique, so a test can grep the whole parse output for
# them without risking a collision with real prose.
BOILERPLATE_MARKERS = (
    "SUBSCRIBE TO OUR NEWSLETTER",
    "MAIN SITE NAVIGATION",
    "ACCEPT ALL COOKIES",
    "RELATED ARTICLES YOU MAY LIKE",
    "COPYRIGHT NOTICE FOOTER",
    "TRACKING SCRIPT PAYLOAD",
    "ADVERTISEMENT SLOT",
)

# (heading tag, heading text, paragraphs). The tags start at h2 on purpose: the
# site title owns the h1, which is what most CMS templates do, and the parser
# must still dense-rank these onto levels 1 and 2 or `HARD_BOUNDARY_LEVEL` never
# fires and the document gets no hard chunk boundary anywhere.
SECTIONS: list[tuple[str, str, list[str]]] = [
    (
        "h2",
        "Vectors",
        [
            "A vector is an ordered list of numbers. Vectors add componentwise and scale by a "
            "real number, and the zero vector is the additive identity for that addition.",
            "Geometrically a vector in the plane is an arrow with a length and a direction, so "
            "two vectors are equal exactly when they agree in both.",
        ],
    ),
    (
        "h3",
        "The Dot Product",
        [
            "The dot product of two vectors multiplies matching components and sums the results, "
            "returning a single number rather than a vector.",
            "The dot product is zero exactly when the two vectors are perpendicular, which makes "
            "it the basic test for orthogonality in any inner product space.",
        ],
    ),
    (
        "h3",
        "Norms and Distance",
        [
            "The norm of a vector is the square root of its dot product with itself, and the "
            "distance between two points is the norm of their difference.",
        ],
    ),
    (
        "h2",
        "Matrices",
        [
            "A matrix is a rectangular array of numbers. Matrix addition is componentwise and "
            "multiplying a matrix by a scalar multiplies every entry of it.",
        ],
    ),
    (
        "h3",
        "Matrix Multiplication",
        [
            "To multiply two matrices, take the dot product of row i of the first matrix with "
            "column j of the second to produce the entry in row i, column j of the result.",
            "Matrix multiplication is associative but not commutative, and it requires the inner "
            "dimensions of the two matrices to agree.",
        ],
    ),
    (
        "h2",
        "Linear Independence",
        [
            "A set of vectors is linearly independent when no vector in the set can be written as "
            "a combination of the others.",
            "Independence is what makes a spanning set a basis, and it is checked by solving a "
            "homogeneous system and finding only the trivial solution.",
        ],
    ),
]


def build_sample_html(title: str = "Linear Algebra, Abridged") -> bytes:
    """Return the bytes of a short multi-section article wrapped in site chrome."""
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head>',
        '<meta charset="utf-8">',
        f"<title>{title}</title>",
        '<script>var tracker = "TRACKING SCRIPT PAYLOAD";</script>',
        "<style>body { font-family: serif; } /* ADVERTISEMENT SLOT */</style>",
        "</head><body>",
        # Site chrome. `<header>` is only stripped when it is a direct child of
        # a `<body>` that had to be elected as the content root -- here `<main>`
        # wins, so this is dropped by being outside the root instead.
        '<header class="site-header"><nav aria-label="MAIN SITE NAVIGATION">'
        "<ul><li><a href=/>Home</a></li><li><a href=/about>About</a></li></ul>"
        "<p>MAIN SITE NAVIGATION</p></nav></header>",
        '<div class="cookie-consent-banner"><p>ACCEPT ALL COOKIES</p></div>',
        '<div class="ad-slot"><p>ADVERTISEMENT SLOT</p></div>',
        "<main>",
        f"<h1>{title}</h1>",
        "<p>This article reviews the small amount of linear algebra needed later. "
        "It assumes only arithmetic and a willingness to write things in a list.</p>",
    ]

    for index, (tag, heading, paragraphs) in enumerate(SECTIONS):
        parts.append(f'<{tag} id="{heading.lower().replace(" ", "-")}">{heading}</{tag}>')
        for paragraph in paragraphs:
            parts.append(f"<p>{paragraph}</p>")
        # Drop the interstitial into the middle of the article, where a naive
        # "strip the first and last block" rule would never look for it.
        if index == 1:
            parts.append(
                '<aside class="newsletter-signup"><h3>SUBSCRIBE TO OUR NEWSLETTER</h3>'
                "<p>SUBSCRIBE TO OUR NEWSLETTER for weekly updates.</p>"
                '<form><input name="email"><button>Sign up</button></form></aside>'
            )

    parts.extend(
        [
            '<div class="related-posts"><h2>RELATED ARTICLES YOU MAY LIKE</h2>'
            "<ul><li>RELATED ARTICLES YOU MAY LIKE</li></ul></div>",
            "</main>",
            '<footer><p>COPYRIGHT NOTICE FOOTER</p></footer>',
            "</body></html>",
        ]
    )
    return "\n".join(parts).encode("utf-8")


def build_flat_html(heading_tag: str = "h3", sections: int = 5) -> bytes:
    """A page whose only headings are one deep tag -- an `h3`-only blog.

    Exists to pin the dense-ranking rule: the shallowest observed tag must come
    out as level 1 whatever digit it carries.
    """
    parts = ["<!DOCTYPE html><html><head><title>Flat</title></head><body><article>"]
    for index in range(sections):
        parts.append(f"<{heading_tag}>Topic number {index}</{heading_tag}>")
        parts.append(
            f"<p>Topic number {index} is explained here at enough length to survive the "
            f"chunker's minimum token count, which needs a genuine paragraph rather than "
            f"a caption. It concerns vectors, matrices, and the algebra that relates them.</p>"
        )
    parts.append("</article></body></html>")
    return "\n".join(parts).encode("utf-8")


def build_long_section_html(paragraphs: int = 40) -> bytes:
    """One heading with far more than `PAGE_CHARS` of prose under it.

    Pins the other half of pagination: a section longer than a page must spill
    onto continuation pages that carry no heading of their own.
    """
    body = "".join(
        f"<p>Paragraph {index} of a deliberately long section about linear transformations, "
        f"their matrices, and the change of basis that relates two such matrices to each "
        f"other. It is padded so the section exceeds one synthetic page.</p>"
        for index in range(paragraphs)
    )
    return (
        "<!DOCTYPE html><html><head><title>Long</title></head><body><main>"
        f"<h1>Linear Transformations</h1>{body}</main></body></html>"
    ).encode("utf-8")
