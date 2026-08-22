"""Build the skill graph's spine from a document's own table of contents.

A textbook's TOC is a concept hierarchy the author already curated, in teaching
order. Using it as the structure -- rather than asking a model to infer one from
loose prose -- fixes the failure this module exists to answer: LLM-inferred
extraction on a real 89-page optimisation textbook produced nodes called
"Consider", "Slacky", "Endpoint", "Accessed" and "1 0", strung into a 17-deep
chain. The TOC for the same book reads "Matrix product", "Simplex Algorithm
Procedure", "The KKT Theorem", "Cutting Planes".

The model's job moves from *inventing structure* to *describing content that
already has structure*, which is the thing models are actually reliable at.

Pure: no I/O, no database, no LLM. Every decision here is testable in
milliseconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.dag import CandidateEdge
from app.ingestion.parsers.base import TocEntry

__all__ = [
    "TocNode",
    "FRONT_BACK_MATTER",
    "DIFFICULTY_MIN",
    "DIFFICULTY_MAX",
    "is_front_or_back_matter",
    "is_generic_section",
    "build_toc_nodes",
    "build_introduces_edges",
    "section_labels",
    "owner_of_page",
    "is_drillable",
    "difficulty_from_depth",
    "slugify",
]

# Front and back matter carry no skills. Leaving them in is how a graph ends up
# with a node called "Accessed", scraped from "[Accessed: 3/11/2024]" in a
# bibliography -- or, on a converted ebook whose outline is mostly boilerplate,
# a 2967-page textbook that yields nothing but "Title Page" and "Copyright Page".
FRONT_BACK_MATTER = frozenset(
    """preface foreword acknowledgements acknowledgments contents references bibliography index
    appendix glossary colophon dedication about-the-author about-the-authors copyright notation
    errata table-of-contents further-reading credits title cover imprint frontmatter backmatter
    endnotes footnotes permissions disclaimer trademarks isbn epilogue prologue afterword
    list-of-figures list-of-tables reader-reviews""".split()
)

# Matched against the front of a normalised title. Exact-slug matching alone is
# too brittle: real outlines say "Table of Contents (summary)", "Copyright Page",
# "About the Author of This Book". Kept deliberately specific -- a bare "index"
# prefix would eat a legitimate chapter called "Index Notation for Tensors".
FRONT_BACK_PREFIXES = (
    "table of contents",
    "about the author",
    "about this book",
    "about the technical",
    "how to use this book",
    "how to use this ebook",
    "praise for",
    "authors of",
    "creators of",
    "copyright",
    "title page",
    "list of figures",
    "list of tables",
    "index of contents",
)

# Section names that are meaningless as a *skill*. Not dropped -- they usually
# have real content behind them -- but qualified with their parent, so the tree
# says "Formulations: Overview" rather than a node called "Overview".
GENERIC_SECTION_TITLES = frozenset(
    """overview introduction summary conclusion conclusions background motivation
    preliminaries definitions notation examples example exercises problems review
    discussion results methods method materials outline remarks notes""".split()
)

_NUMBER_PREFIX = re.compile(r"^\s*(?:chapter|section|part|appendix)?\s*\d+(?:\.\d+)*[.)]?\s+", re.IGNORECASE)
_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")
_TRAILING_NOISE = re.compile(r"\s+(?:page|section|chapter)$", re.IGNORECASE)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:64].strip("-") or "concept"


def _normalise_for_matching(title: str) -> str:
    """Lowercase, drop a trailing parenthetical, drop a trailing "Page"."""
    text = _NUMBER_PREFIX.sub("", title).strip().lower()
    text = _TRAILING_PARENTHETICAL.sub("", text)
    text = _TRAILING_NOISE.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" .:-")


def is_front_or_back_matter(title: str) -> bool:
    normalised = _normalise_for_matching(title)
    if slugify(normalised) in FRONT_BACK_MATTER:
        return True
    # Whole-word prefix only. A bare `startswith` match would drop a chapter
    # called "Copyrighting Software" because it begins with "copyright".
    return any(
        normalised == prefix or normalised.startswith(prefix + " ") for prefix in FRONT_BACK_PREFIXES
    )


def is_generic_section(title: str) -> bool:
    return slugify(_normalise_for_matching(title)) in GENERIC_SECTION_TITLES


def _clean_title(title: str) -> str:
    """Strip a leading "3.2.1" -- the number is position, not name.

    Kept out of the slug too, so a second edition that renumbers its chapters
    still merges against the first rather than duplicating every node.
    """
    stripped = _NUMBER_PREFIX.sub("", title).strip()
    return stripped or title.strip()


@dataclass(frozen=True, slots=True)
class TocNode:
    slug: str
    title: str
    level: int
    page_start: int
    # Exclusive. The page the next entry at any level begins on, or the last
    # page of the document for the final entry.
    page_end: int
    parent_slug: str | None
    has_children: bool


def _dedupe_slug(slug: str, seen: dict[str, int]) -> str:
    """"Overview" appears once per chapter in many books; they are different
    sections and must not collapse into one node."""
    if slug not in seen:
        seen[slug] = 1
        return slug
    seen[slug] += 1
    return f"{slug}-{seen[slug]}"


def _dedupe_title(title: str, parent_title: str | None, claimed: set[str]) -> str:
    """Make a node's title unique within the document, cheapest change first.

    Unlike a slug, a title is what the learner reads, so the fallback ordinal is
    a last resort rather than the mechanism.
    """
    for candidate in (title, f"{parent_title}: {title}" if parent_title else None):
        if candidate is not None and candidate.casefold() not in claimed:
            claimed.add(candidate.casefold())
            return candidate

    suffix = 2
    while f"{title} ({suffix})".casefold() in claimed:
        suffix += 1
    unique = f"{title} ({suffix})"
    claimed.add(unique.casefold())
    return unique


def build_toc_nodes(entries: list[TocEntry], page_count: int) -> list[TocNode]:
    """Flatten the outline into nodes with parent links and page ranges."""
    usable = [entry for entry in entries if not is_front_or_back_matter(entry.title)]
    if not usable:
        return []

    # Boundaries come from the FULL outline, not the filtered one. Dropping
    # "References" from the node list must not hand its pages to the last real
    # section -- otherwise the final chapter's drills quote the bibliography.
    def next_boundary(after_index: int) -> int:
        for entry in entries[after_index + 1 :]:
            if entry.page_index > entries[after_index].page_index:
                return entry.page_index
        return page_count

    positions = {id(entry): index for index, entry in enumerate(entries)}

    # Normalise levels: a book whose outline starts at level 2 should still have
    # its shallowest entries treated as chapters.
    base_level = min(entry.level for entry in usable)

    slugs: list[str] = []
    seen: dict[str, int] = {}
    for entry in usable:
        slugs.append(_dedupe_slug(slugify(_clean_title(entry.title)), seen))

    nodes: list[TocNode] = []
    claimed_titles: set[str] = set()
    # stack[i] is (level, slug, title) of the most recent ancestor at that level.
    stack: list[tuple[int, str, str]] = []

    for index, entry in enumerate(usable):
        level = entry.level - base_level + 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        parent_title = stack[-1][2] if stack else None

        # A node's own text ends where the NEXT entry begins, regardless of that
        # entry's level -- children live inside the parent's range.
        page_end = next_boundary(positions[id(entry)])
        has_children = index + 1 < len(usable) and (usable[index + 1].level - base_level + 1) > level

        # "Overview" is not a skill. Qualified with its parent it becomes one --
        # "Formulations: Overview" -- which keeps the section's real content
        # instead of dropping it, and stops every chapter's first section
        # looking identical in the tree.
        title = _clean_title(entry.title)
        if parent_title is not None and is_generic_section(title):
            title = f"{parent_title}: {title}"
        # Slugs were deduped above; titles were not, so an outline that names
        # two sections identically -- STAT 231 has two "Functions of Random
        # Variables" -- produced two nodes a learner cannot tell apart, and two
        # skills the prerequisite pass matches on the same words. Qualify with
        # the parent first, since that is usually what distinguishes them, and
        # only number them when even that collides.
        title = _dedupe_title(title, parent_title, claimed_titles)

        nodes.append(
            TocNode(
                slug=slugs[index],
                title=title,
                level=level,
                page_start=entry.page_index,
                page_end=max(page_end, entry.page_index + 1),
                parent_slug=parent,
                has_children=has_children,
            )
        )
        stack.append((level, slugs[index], title))

    return nodes


INTRODUCES_CONFIDENCE = 0.45


def build_introduces_edges(nodes: list[TocNode], drillable: set[str]) -> list[CandidateEdge]:
    """Parent -> child, but ONLY where the parent is a skill in its own right.

    The outline used to contribute one edge per entry at 0.95. That made half the
    graph a table of contents and every chapter a root, which is a filing system,
    not a dependency structure. `section_labels` explains why that went.

    What survives is the narrow case where the containment is not merely
    containment. `is_drillable` is the test, and it is the same one that decides
    whether a heading is a node at all: a heading owns a chunk exactly when it
    has prose belonging to no one else. CO 250's "Integer programs" spends page
    75 on why an IP is harder than an LP before its first subsection begins --
    so it teaches something, and "Cutting planes" genuinely follows it. "Duality"
    owns nothing, is not a node, and cannot precede anything.

    Measured on CO 250, this is the difference between recall 0.353 and 0.397 at
    identical precision: five edges, every one between two real skills.

    Confidence sits BELOW every content-derived edge (`MIN_CONFIDENCE` is 0.5)
    rather than above them, which inverts the old ordering deliberately. When a
    structural claim and a claim read out of the prose disagree during cycle
    resolution, the prose should win -- it is evidence about the material, and
    this is an inference from where the material was printed.
    """
    return [
        CandidateEdge(
            prereq=node.parent_slug,
            target=node.slug,
            confidence=INTRODUCES_CONFIDENCE,
            support=1,
        )
        for node in nodes
        if node.parent_slug is not None and node.parent_slug in drillable and node.slug in drillable
    ]


def section_labels(nodes: list[TocNode]) -> dict[str, str]:
    """The top-level heading each entry sits under, as a LABEL rather than a node.

    The outline is a containment tree, and containment is not a prerequisite
    relation. This used to be `build_toc_spine`, which emitted one
    parent -> child edge per entry at confidence 0.95. Measured on CO 250 that
    was 38 of 77 edges -- half the graph was the table of contents, asserted
    more strongly than every edge actually derived from the prose, whose best
    was 0.90. "Linear Programs is a prerequisite for Basis" is a page-range
    fact wearing a prerequisite's clothes: the two are not related by knowledge,
    they are related by having been printed near each other.

    It also produced the wrong shape. Every chapter became a root, every skill
    hung beneath one, and the canvas rendered the book's contents page instead
    of the dependency structure the product exists to show.

    So the chapter survives as provenance -- "this skill came from Duality" is
    worth knowing, and is what a learner uses to find their place in the book --
    while the graph is left to the content passes, which answer a different
    question and are the only ones that can.

    Nothing is lost that was carried: `score.py` already dropped every
    container-incident edge from both sides before scoring, so the measured
    recall and precision of the graph are unchanged by this. What changes is
    what the learner sees.
    """
    by_slug = {node.slug: node for node in nodes}
    labels: dict[str, str] = {}

    for node in nodes:
        # Walk to the outermost ancestor. A top-level entry labels itself, which
        # is what makes "Duality" a section name rather than a special case.
        current = node
        seen = {current.slug}
        while current.parent_slug is not None and current.parent_slug in by_slug:
            parent = by_slug[current.parent_slug]
            if parent.slug in seen:
                break
            seen.add(parent.slug)
            current = parent
        labels[node.slug] = current.title

    return labels


def owner_of_page(nodes: list[TocNode], page_index: int) -> TocNode | None:
    """The single node a page's content belongs to: the DEEPEST match.

    Ranges nest, so a page inside "Matrix product" is also inside its parent
    chapter "Prerequisite knowledge". Letting both claim it gives the chapter a
    summary lifted from its first section and a drill question about material it
    only introduces -- which is exactly what happened before this existed.

    Assigning to the deepest match instead leaves pure container headings owning
    nothing, which is the correct signal that they are structure, not lessons.
    """
    best: TocNode | None = None
    for node in nodes:
        if node.page_start <= page_index < node.page_end:
            # Deeper wins; at equal depth the later-starting entry wins, since
            # it is the more specific one on a shared page.
            if best is None or (node.level, node.page_start) > (best.level, best.page_start):
                best = node
    return best


def is_drillable(node: TocNode, owned_chunks: int) -> bool:
    """Does this heading have a skill of its own, or is it only structure?

    **The test is exclusive chunk ownership, not the shape of the outline.**
    `owner_of_page` gives every chunk to the DEEPEST heading whose page range
    contains it, so "owns at least one chunk" means "has prose that belongs to
    no one else" -- which is exactly the material a drill question would be
    generated from and graded against. A heading that owns nothing has nothing
    to ask about.

    That one test catches two different populations, which is why it is stated
    as ownership rather than as either of them:

    *Pure containers.* A chapter whose first section starts on the chapter's own
    opening page owns no page exclusively. CO 250 has seven of these
    ("Duality", "Linear programs", ...) and they were the graph's only entry
    points -- five headings with nothing behind them.

    *Headings whose range yields no chunk at all.* A section too short to
    survive the chunker's minimum, or a slide-deck bookmark pointing at a page
    of figures. Measured across six books these overlap with containers but are
    not the same set: MATH 239 has eight containers and three empty headings.

    `has_children` is the tempting one-liner and it is wrong. CO 250's "Integer
    programs" spends page 75 on why an IP is harder than an LP before its first
    subsection begins on page 76: it has children AND a genuine skill, it owns
    that page's chunks, and a structural test would blank it.
    """
    return owned_chunks > 0


DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 5


def difficulty_from_depth(depth: int, max_depth: int) -> int:
    """Difficulty is position in the DEPENDENCY graph, not in the outline.

    Outline nesting was the previous signal and it inverted on real books. A
    chapter came out at 2 while every section inside it came out at 4-5, so the
    container was "easier" than all of its own content. And CO 250's convex
    hulls -- chapter 4, page 76 -- outranked the KKT theorem, page 86 and the
    last section in the book, purely because the KKT section happened to sit one
    level shallower in the table of contents. Numbering depth is how an author
    organised a document, not how hard the material is.

    Prerequisite depth is the thing that predicts difficulty: a node reachable
    only after clearing five other skills is harder than one a learner can open
    the book at, whatever the section numbering says. It also makes the value
    self-consistent with `skill_nodes.depth`, since both come from the same
    `topological_depths` call in `persist_graph`.

    The span never shrinks below the four steps of the 1-5 scale, so a shallow
    graph maps depth d to d+1 instead of stretching three layers across the
    whole range and calling every leaf "Advanced".
    """
    steps = DIFFICULTY_MAX - DIFFICULTY_MIN
    span = max(max_depth, steps)
    scaled = DIFFICULTY_MIN + round(max(depth, 0) / span * steps)
    return max(DIFFICULTY_MIN, min(DIFFICULTY_MAX, scaled))
