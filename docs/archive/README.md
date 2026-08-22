# Archive

This directory holds the documentation for **Learn-Anything**, the textbook
product this repository began as. It is kept because the code it describes is
still running — not because it is dead.

## Why the docs moved but the code did not

Learn-Anything ingested a PDF, a web page, or a URL, read the document's own
table of contents, and built a prerequisite DAG of skills you could drill and
forget on an SM-2 schedule. The product is now
[ScaleUp](../../README.md): the same DAG, the same decay, the same
EXP — applied to playing an instrument rather than reading a textbook.

The ingestion pipeline was not retired in that move. It became the **curriculum
compiler's source path**: a method book, a syllabus, or an exercise catalogue is
ingested exactly the way a textbook was, and the resulting sections become
candidate skills and quote-backed prerequisite edges for a curriculum version to
review and publish. The violin tree in `app/seed.py` is generated that way today
— it has no violin-specific graph code at all.

So `app/ingestion/`, `app/services/ingest_*.py`, `app/services/qa_service.py`,
`app/services/search_service.py`, the `explore` and `jobs` routers, the Chroma
index, and the Neo4j projection are all live, tested, and load-bearing. Only the
*framing* was archived.

## What is here

| Document | What it covers | Still accurate? |
|---|---|---|
| [`graph_extraction_contract.md`](graph_extraction_contract.md) | The six ingestion stages — parse, chunk, map, reduce, cycle rejection, persist — plus the TOC-first extraction rules, structural nodes, and difficulty derivation. | Yes. This is the live contract for `app/ingestion/`; it is filed here because its worked examples are textbooks. |
| [`textbook-product.md`](textbook-product.md) | The original product description, the explore/search/ask surfaces, and the measured extraction-quality numbers. | The description is historical. The measurements still stand and are the reason sub-section segmentation is off by default. |

## Where the live documents are

- [`../../README.md`](../../README.md) — the product now
- [`../roadmap.md`](../roadmap.md) — the live work board
- [`../api_contract.md`](../api_contract.md) — the backend/frontend seam
- [`../srs_and_exp.md`](../srs_and_exp.md) — retention mechanics, unchanged by the pivot
- [`../deployment.md`](../deployment.md) — managed-cloud packaging
