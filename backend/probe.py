"""Run the shipping ingest graph over a PDF offline and dump it as JSON.

Calls `ingest_pipeline._toc_graph` itself rather than reimplementing it. An
earlier version of this file copied the pipeline's logic and drifted from it --
it held `CONTAINER_CHUNK_FALLBACK = 3` while production used `2`, so every
number measured with it described a pipeline that was not shipping. Anything
this probe still owns is here because it needs a database and cannot be reached
without one.

Usage: python probe.py <pdf> <out.json> [--segment] [--no-reverse] [--old-fake]

    --segment      split sections on the book's own concept boundaries
    --no-reverse   forward prerequisite pass only
    --old-fake     restrict the FakeProvider to verbatim-title matching

The three flags exist so each stage's contribution stays attributable. The
reverse pass and the smarter fake are worth nothing apart and only pay off
together, which is a claim that has to stay reproducible rather than sit in a
report.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass

from app.config import get_settings
from app.domain.dag import build_acyclic_edges, topological_depths
from app.ingestion import prereqs
from app.ingestion.chunking import chunk_blocks
from app.ingestion.parsers.pdf import parse_pdf
from app.ingestion.prereqs import SkillRef, infer_prerequisites
from app.ingestion.toc import build_toc_nodes, difficulty_from_depth
from app.llm import fake_provider
from app.llm.fake_provider import FakeLLMClient
from app.services.ingest_pipeline import _toc_graph, chunk_id_for

pdf, out = sys.argv[1], sys.argv[2]
reverse = "--no-reverse" not in sys.argv

# Segmentation ships off (see `Settings.segment_sections`); `--segment` turns it
# on for measurement without editing the environment.
get_settings().segment_sections = "--segment" in sys.argv

for argument in sys.argv:
    # `--rset=NAME=VALUE` / `--set=NAME=VALUE` override a tuning constant in
    # `ingestion.prereqs` / `llm.fake_provider` for one run, so the sensitivity
    # of a number to a threshold can be measured without editing the module.
    if argument.startswith(("--rset=", "--set=")):
        module = prereqs if argument.startswith("--rset=") else fake_provider
        name, _, value = argument.split("=", 1)[1].partition("=")
        setattr(module, name, float(value) if "." in value else int(value))

if "--old-fake" in sys.argv:
    # The original rule: one cue, the title said verbatim. Nothing else fires.
    def _title_only(title, defining_text, frequency, corpus, *, terms=False):
        phrase = " ".join(title.split()).lower()
        return [("phrase", (phrase,), fake_provider.CUE_TITLE_WEIGHT)] if len(phrase) >= 6 else []

    fake_provider._skill_cues = _title_only


@dataclass(frozen=True, slots=True)
class ProbeChunk:
    """Stands in for the ORM Chunk; the pipeline reads only these fields."""

    id: uuid.UUID
    text: str
    page_start: int
    page_end: int
    ordinal: int


@dataclass(frozen=True, slots=True)
class ProbeDocument:
    storage_path: str
    filename: str
    # `_toc_graph` dispatches through `parsers.registry.parse_source` rather than
    # calling `parse_pdf` directly, so the stand-in has to carry the same field
    # the real Document row does. The probe takes a PDF path by construction.
    source_type: str = "pdf"


parsed = parse_pdf(pdf)
document_id = uuid.uuid5(uuid.NAMESPACE_URL, pdf)
chunks = [
    ProbeChunk(
        id=chunk_id_for(document_id, c.ordinal),
        text=c.text,
        page_start=c.page_start,
        page_end=c.page_end,
        ordinal=c.ordinal,
    )
    for c in chunk_blocks(parsed.blocks)
]

concepts, edges = _toc_graph(
    ProbeDocument(storage_path=pdf, filename=pdf.rsplit("/", 1)[-1]),
    chunks,
    parsed.page_count,
    set(),
    set(),
    client=FakeLLMClient(),
    book_title="textbook",
)

# Mirrors `_infer_prereq_edges`, which needs a Session we do not have here.
# Structural nodes are not skills, so they are not in the model's vocabulary.
drillable = [c for c in concepts if c.assessable]
text_by_id = {c.id: c.text for c in chunks}
# Reading order, which is NOT the order `_toc_graph` returns once segmentation
# is on: every outline section comes first and every fragment after. Mirrors the
# same two lines in `ingest_pipeline._infer_prereq_edges`.
ordinal_by_id = {c.id: c.ordinal for c in chunks}


def reading_order(concept) -> int:
    owned = [ordinal_by_id[cid] for cid in concept.source_chunk_ids if cid in ordinal_by_id]
    return min(owned) if owned else 0


outcome = infer_prerequisites(
    FakeLLMClient(),
    "textbook",
    [SkillRef(slug=c.slug, title=c.title, summary=c.summary, order=reading_order(c)) for c in drillable],
    {
        c.slug: " ".join(text_by_id[cid] for cid in c.source_chunk_ids if cid in text_by_id)
        for c in drillable
    },
    reverse=reverse,
)

slugs = {c.slug for c in concepts}
structural_pairs = {(e.prereq, e.target) for e in edges}
accepted, rejected = build_acyclic_edges(slugs, edges + outcome.edges)
depths = topological_depths(slugs, accepted)
max_depth = max(depths.values(), default=0)

containers = {c.slug for c in concepts if not c.assessable}
nodes_by_slug = {n.slug: n for n in build_toc_nodes(parsed.toc, parsed.page_count)}
by_slug = {c.slug: c for c in concepts}

prereqs_of: dict[str, list[str]] = {}
for edge in accepted:
    prereqs_of.setdefault(edge.target, []).append(edge.prereq)


def gating(slug: str, seen: set[str] | None = None) -> list[str]:
    """What actually gates a node, seeing through containers -- the probe's copy
    of `domain.states.gating_masteries`, which needs per-user progress rows."""
    seen = set() if seen is None else seen
    resolved: list[str] = []
    for prereq in prereqs_of.get(slug, ()):
        if prereq in seen:
            pass
        else:
            seen.add(prereq)
            if prereq in containers:
                resolved.extend(gating(prereq, seen))
            else:
                resolved.append(prereq)
    return resolved


startable = sorted(s for s in slugs if s not in containers and not gating(s))
incident = [e for e in accepted if e.prereq in containers or e.target in containers]


def page_span(slug: str) -> tuple[int, int, int]:
    node = nodes_by_slug.get(slug)
    if node is not None:
        return node.level, node.page_start + 1, node.page_end
    # A fragment: locate it by the chunks it owns.
    pages = [text_by_id and c.page_start for c in chunks if c.id in set(by_slug[slug].source_chunk_ids)]
    pages = [p for p in pages if p is not None]
    return 3, (min(pages) + 1 if pages else 1), (max(pages) + 1 if pages else 1)


payload = {
    "nodes": [
        {
            "slug": c.slug,
            "title": c.title,
            "level": page_span(c.slug)[0],
            "page_start": page_span(c.slug)[1],
            "page_end": page_span(c.slug)[2],
            "difficulty": difficulty_from_depth(depths[c.slug], max_depth),
            "depth": depths[c.slug],
            "assessable": c.assessable,
            "section": c.section,
            "summary": c.summary,
            "own_chars": sum(len(text_by_id[cid]) for cid in c.source_chunk_ids if cid in text_by_id),
            "chunk_fallback": False,
            "is_fragment": c.slug not in nodes_by_slug,
        }
        for c in concepts
    ],
    "edges": [
        {
            "prereq": e.prereq,
            "target": e.target,
            "confidence": e.confidence,
            "origin": "structural" if (e.prereq, e.target) in structural_pairs else "inferred",
        }
        for e in accepted
    ],
    "rejected": [
        {"prereq": r.prereq, "target": r.target, "reason": r.reason, "cycle_path": list(r.cycle_path)}
        for r in rejected
    ],
    "depths": depths,
    "stats": {
        "toc_entries": len(parsed.toc),
        "nodes": len(concepts),
        "fragments": sum(1 for c in concepts if c.slug not in nodes_by_slug),
        "chunks": len(chunks),
        "structural_nodes": len(containers),
        "drillable_nodes": len(drillable),
        "structural": len(edges),
        "inferred_kept": len(outcome.edges),
        "accepted": len(accepted),
        "cycle_rejected": len(rejected),
        "max_depth": max_depth,
        "startable_nodes": len(startable),
        "edges_incident_to_structural": len(incident),
        "edges_incident_to_structural_inferred": sum(
            1 for e in incident if (e.prereq, e.target) not in structural_pairs
        ),
        "reverse_calls": outcome.reverse_calls,
        "agreed": outcome.agreed,
        "rejected_crowded": outcome.rejected_crowded,
        "rejected_backward": outcome.rejected_backward,
        "llm_calls": outcome.sections_ok + outcome.sections_failed + outcome.reverse_calls,
        "duplicate_titles": len(concepts) - len({c.title.casefold() for c in concepts}),
    },
}

with open(out, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
print(json.dumps(payload["stats"], indent=2))
