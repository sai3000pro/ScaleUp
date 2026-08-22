"""HTML parsing into the same `ParsedDocument` every other parser emits.

HTML is the format the TOC path was waiting for. `h1`..`h6` are *declared*
heading levels, not a font-size heuristic over a PDF text layer, so the outline
this produces is the author's own -- which means the whole structural half of
ingestion runs with **zero LLM calls** and the node titles are the article's
real section headings.

Three decisions carry the file.

**Boilerplate removal is deterministic and two-staged.** First a tag denylist
(`script`, `nav`, `aside`, `footer`, ...) is `decompose()`d outright; then a
content root is elected -- `main`, then `article`, then `[role=main]`, then
`body` -- and inside it any element whose class or id contains a denylisted
*whole token* is removed. Whole-token matching is the part that matters: a
substring rule drops `<div class="broadcast">` for containing "ad", and a page
that loses a content div is indistinguishable downstream from a page that never
had one.

**Heading levels are dense-ranked over the tags actually observed.** A blog that
uses only `h2` and `h3` must still yield levels 1 and 2, because
`chunking.HARD_BOUNDARY_LEVEL` is 2 and a document whose shallowest heading is
level 3 would get no hard chunk boundary anywhere -- one chunk could then span
the whole page and every skill derived from it would be a blend.

**Synthetic pagination** -- see `_paginate`. It is the load-bearing decision in
this file and the invariants it holds are not aesthetic.
"""

from __future__ import annotations

import codecs
import re

from bs4 import (
    BeautifulSoup,
    CData,
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    ProcessingInstruction,
    Tag,
)

from app.ingestion.parsers.base import ParsedBlock, ParsedDocument, TocEntry
from app.ingestion.parsers.clean import normalise_html_text

__all__ = ["parse_html", "parse_html_bytes", "decode_html", "document_title", "PAGE_CHARS"]

# Every one of these subclasses NavigableString, so a plain isinstance check
# treats an HTML comment as body text. Real pages are full of them -- ad-server
# markers, template debris, whole commented-out sections -- and a learner would
# see them as prose in a drill.
NON_TEXT_STRINGS = (Comment, Doctype, CData, Declaration, ProcessingInstruction)

# One synthetic page holds one heading plus roughly this much prose. Sized to
# sit near the 800-token chunk budget so a page is a small number of chunks:
# large enough that a section is not shattered across pages it does not need,
# small enough that a 40-page web article does not collapse into one page and
# hand every chunk to a single node.
PAGE_CHARS = 3000

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
MAX_HEADING_DEPTH = len(HEADING_TAGS)

# Tags whose text is one block. `td`/`th` are included because data tables in
# technical writing are content; `pre` because a code listing is one unit and
# joining it with the paragraph after it would produce a chunk that is half
# prose and half syntax.
TEXT_TAGS = ("p", "li", "dd", "dt", "blockquote", "pre", "figcaption", "caption", "td", "th")

# Flowed into the surrounding text rather than broken out. Without this every
# `<a>` in a paragraph becomes its own block and the paragraph is shredded into
# link text and the words between links.
INLINE_TAGS = frozenset(
    """a span em strong b i u s code sub sup small abbr cite q mark time kbd var samp del ins
    bdi bdo ruby rt rp wbr font tt big strike label output data dfn math semantics mrow mi mo mn
    msup msub mfrac msqrt annotation""".split()
)

# Never content, in any document. `form`/`button`/`input` go too: a search box
# contributes the word "Search" and a submit label, which is noise in an
# embedding and a distractor in a prompt.
DROP_TAGS = (
    "script", "style", "noscript", "template", "iframe", "svg", "canvas", "object", "embed",
    "video", "audio", "source", "track", "map", "area", "form", "button", "input", "select",
    "textarea", "fieldset", "legend", "datalist", "optgroup", "option", "dialog", "meta", "link",
    "nav", "aside", "footer",
)

# Whole tokens, matched against `class` and `id` split on any non-alphanumeric.
# Every entry here is a thing that appears on a page but is not *of* the page.
DENY_TOKENS = frozenset(
    """nav navigation navbar navbox menu sidebar sidenav breadcrumb breadcrumbs footer banner
    masthead ad ads advert adverts advertisement sponsored promo promotion newsletter subscribe
    signup social share sharing comment comments disqus related recommended trending popup modal
    overlay cookie cookies consent gdpr paywall toolbar skip skiplink screenreader sronly
    visuallyhidden noprint editsection catlinks printfooter sitenotice sitesub jumplink
    pagination pager widget toc headerlink permalink anchorlink""".split()
)

# Documentation generators append a self-link to every heading -- Sphinx a
# pilcrow, Docusaurus a hash, MkDocs a link glyph -- so "3.1. Numbers" arrives
# as "3.1. Numbers ¶" and becomes a node titled that. Measured on
# docs.python.org, where every one of the six headings carried it.
#
# The leading `\s+` is not decoration: without it this renames "Learning C#" to
# "Learning C". A real heading does not end in a space followed by one of these.
_HEADING_ANCHOR = re.compile(r"\s+[¶#§¤🔗⚓↩︎]+$")


def _token_set(value: object) -> set[str]:
    """Class/id attribute -> lowercase alphanumeric tokens.

    `class` arrives as a list and `id` as a string, and either may contain
    hyphens, underscores, or camel case runs. Splitting on every non-alphanumeric
    character is what makes "site-footer" match "footer" while "broadcast" does
    not match "ad".
    """
    if isinstance(value, list):
        raw = " ".join(str(item) for item in value)
    elif value is None:
        raw = ""
    else:
        raw = str(value)

    token = ""
    tokens: set[str] = set()
    for char in raw.lower():
        if char.isalnum():
            token += char
        else:
            if token:
                tokens.add(token)
            token = ""
    if token:
        tokens.add(token)
    return tokens


def _is_boilerplate(element: Tag) -> bool:
    tokens = _token_set(element.get("class")) | _token_set(element.get("id"))
    if tokens & DENY_TOKENS:
        return True
    # ARIA says these outright. `presentation`/`none` is a layout table telling
    # us it carries no meaning, which is exactly the claim we want to believe.
    return str(element.get("role", "")).lower() in {"navigation", "banner", "complementary", "search"}


def _content_root(soup: BeautifulSoup) -> Tag:
    """Elect the subtree that holds the article.

    Ordered by how strong a claim the element makes. `<main>` is unambiguous and
    unique per document; `<article>` is nearly so; `role="main"` is the pre-HTML5
    spelling of the same thing; `<body>` is the admission that the page said
    nothing about its own structure.
    """
    for finder in (
        lambda: soup.find("main"),
        lambda: soup.find("article"),
        lambda: soup.find(attrs={"role": "main"}),
        lambda: soup.find("body"),
    ):
        found = finder()
        if isinstance(found, Tag):
            return found
    return soup


def _strip(soup: BeautifulSoup) -> Tag:
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()

    root = _content_root(soup)

    # A site header is chrome; an `<article><header>` is the article's own title
    # block and is content. The difference is exactly whether the root had
    # something better to offer than `<body>`, so it is decided here rather than
    # by adding `header` to DROP_TAGS.
    if root.name == "body":
        for header in root.find_all("header", recursive=False):
            header.decompose()

    # Collect before decomposing: mutating the tree under an active generator
    # skips siblings.
    doomed = [element for element in root.find_all(True) if _is_boilerplate(element)]
    for element in doomed:
        element.decompose()

    return root


def _text_of(element: Tag) -> str:
    return normalise_html_text(element.get_text(" ", strip=True))


# A page from a URL is attacker-supplied and `html.parser` will happily build a
# tree thousands of levels deep from `<div>` repeated. Below this the subtree is
# flattened with `get_text` instead of descended into, so a hostile page costs a
# worse parse rather than a RecursionError inside a Celery task.
MAX_DEPTH = 100


def _collect(node: Tag, out: list[tuple[int | None, str]], pending: list[str], depth: int = 0) -> None:
    """Depth-first walk emitting (heading_level | None, text) in document order.

    Recursive descent rather than `find_all`, because a `<div>` whose text is not
    wrapped in a `<p>` is common enough that losing it is not acceptable, and a
    flat scan for block tags cannot see it.
    """

    def flush() -> None:
        joined = normalise_html_text(" ".join(pending))
        pending.clear()
        if joined:
            out.append((None, joined))

    for child in node.children:
        if isinstance(child, NON_TEXT_STRINGS):
            pass
        elif isinstance(child, NavigableString):
            text = str(child)
            if text.strip():
                pending.append(text)
        elif not isinstance(child, Tag):
            pass
        elif child.name in HEADING_TAGS:
            flush()
            text = _HEADING_ANCHOR.sub("", _text_of(child))
            if text:
                out.append((int(child.name[1]), text))
        elif child.name in TEXT_TAGS:
            flush()
            text = _text_of(child)
            if text:
                out.append((None, text))
        elif child.name == "br":
            pending.append(" ")
        elif child.name in INLINE_TAGS:
            text = _text_of(child)
            if text:
                pending.append(text)
        elif depth >= MAX_DEPTH:
            text = _text_of(child)
            if text:
                pending.append(text)
        else:
            # A container: its own loose text belongs before its children, not
            # merged across them.
            flush()
            _collect(child, out, pending, depth + 1)
            flush()

    flush()


def _dense_rank_levels(items: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    """Map the heading tags a document actually uses onto 1..n.

    A page whose shallowest heading is `h2` is not a page of subsections -- the
    author simply reserved `h1` for the site title, or the CMS did. Ranking the
    observed tags rather than trusting the digit is what keeps
    `chunking.HARD_BOUNDARY_LEVEL = 2` reachable on such a document, and what
    stops `build_toc_nodes` treating a flat `h3`-only page as three levels of
    nesting.
    """
    observed = sorted({level for level, _ in items if level is not None})
    rank = {level: index + 1 for index, level in enumerate(observed)}
    return [(rank[level] if level is not None else None, text) for level, text in items]


def _paginate(items: list[tuple[int | None, str]]) -> ParsedDocument:
    """Assign every block a synthetic page index.

    HTML has no pages, but `page_index` is the addressing unit for chunk
    ownership and for the `SourceRef` a learner is shown, so one has to be
    invented. **One synthetic page = one heading plus its prose**, split at
    `PAGE_CHARS` and never mid-block.

    Two invariants, and they are load-bearing rather than tidy:

    *Every heading starts a page.* `build_toc_nodes.next_boundary` only advances
    past an entry with a **strictly greater** page index, so a heading sharing a
    page with the one before it gets that entry's range as well as its own.

    *No page holds two headings.* `toc.owner_of_page` gives a chunk to the
    DEEPEST node whose range contains it. If an `h2` and its first `h3` landed on
    the same index their ranges would be identical, the `h3` would take every
    chunk in both, and `is_drillable` -- which is `owned_chunks > 0` -- would
    turn the `h2` structural. Collapse every heading onto page 0 and the entire
    graph becomes un-drillable, with no error anywhere.
    """
    # Every heading ends a chunk, at any depth. An HTML heading is declared by
    # the author rather than inferred from typography, so unlike a PDF's it
    # cannot be a false positive that shreds a paragraph -- and letting two
    # declared sections share a chunk means the deeper one's prose is credited
    # to the shallower one by `owner_of_page`, which is the container problem
    # `toc.is_drillable` exists to expose.
    parsed = ParsedDocument(hard_boundary_level=MAX_HEADING_DEPTH)
    pages: list[list[str]] = []
    page_chars = 0

    for level, text in items:
        if level is not None:
            # Unconditional, even when the current page is empty: two headings in
            # a row (an `h2` immediately followed by its first `h3`) is the exact
            # case the second invariant exists for.
            pages.append([])
            page_chars = 0
        elif not pages:
            # Prose before the first heading -- an article lead, usually.
            pages.append([])
            page_chars = 0
        elif page_chars + len(text) > PAGE_CHARS:
            pages.append([])
            page_chars = 0
        else:
            pass

        index = len(pages) - 1
        pages[index].append(text)
        page_chars += len(text) + 1

        parsed.blocks.append(ParsedBlock(text=text, page_index=index, heading_level=level))
        if level is not None:
            parsed.toc.append(TocEntry(level=level, title=text, page_index=index))

    parsed.page_texts = ["\n".join(page) for page in pages]
    return parsed


# ── decoding ──────────────────────────────────────────────────────────────

_CHARSET_DECLARATION = re.compile(
    rb"""(?:<\?xml[^>]*?encoding\s*=\s*["']([\w.:+-]+)["']"""
    rb"""|<meta[^>]*?charset\s*=\s*["']?([\w.:+-]+))""",
    re.IGNORECASE,
)

# Only the first stretch is searched, matching what a browser does: a charset
# declared after the head is too late to be honoured and is usually a quotation.
_DECLARATION_SEARCH_BYTES = 4096

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode_html(payload: bytes | str) -> str:
    """Bytes -> text, deterministically.

    BeautifulSoup will happily do this itself, and that is precisely the problem:
    its `UnicodeDammit` runs a statistical guess whose answer depends on which
    optional charset libraries happen to be installed in the environment. A page
    containing a control character was measured decoding as MacRoman here, which
    turned every non-ASCII character into mojibake -- silently, since the parse
    still succeeded and produced plausible-looking blocks.

    So the order is fixed and stated: BOM, then the document's own declaration,
    then UTF-8, then CP-1252 with replacement. The last step is the WHATWG
    fallback for an unlabelled legacy page and it cannot fail, which means this
    function never raises and an ingest never dies on an encoding.
    """
    if isinstance(payload, str):
        return payload

    for bom, codec in _BOMS:
        if payload.startswith(bom):
            return payload.decode(codec, errors="replace")

    match = _CHARSET_DECLARATION.search(payload[:_DECLARATION_SEARCH_BYTES])
    candidates: list[str] = []
    if match is not None:
        declared = (match.group(1) or match.group(2) or b"").decode("ascii", errors="ignore")
        if declared:
            candidates.append(declared)
    candidates.append("utf-8")

    for candidate in candidates:
        try:
            return payload.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            pass

    return payload.decode("cp1252", errors="replace")


def document_title(payload: bytes | str) -> str | None:
    """The page's own name, for `Document.filename`.

    `<title>` first because it is what a browser tab and a bookmark show; the
    first `h1` second, because plenty of CMS templates put the site name in
    `<title>` and the article name in the heading.
    """
    soup = BeautifulSoup(decode_html(payload), "html.parser")
    for element in (soup.find("title"), soup.find("h1")):
        if isinstance(element, Tag):
            text = normalise_html_text(element.get_text(" ", strip=True))
            if text:
                return text[:300]
    return None


def parse_html_bytes(payload: bytes | str) -> ParsedDocument:
    # "html.parser" is named explicitly rather than left to BeautifulSoup's
    # preference order, which would silently pick lxml if it were ever installed
    # as somebody else's transitive dependency and change parse results with no
    # commit to blame. lxml is deliberately not a dependency here: it has the
    # same Windows-wheel problem `pyproject.toml` records for chroma-hnswlib.
    soup = BeautifulSoup(decode_html(payload), "html.parser")
    root = _strip(soup)

    items: list[tuple[int | None, str]] = []
    _collect(root, items, [], 0)
    return _paginate(_dense_rank_levels(items))


def parse_html(path: str) -> ParsedDocument:
    with open(path, "rb") as handle:
        return parse_html_bytes(handle.read())
