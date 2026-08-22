"""Score the segmented graph at the granularity the reference can actually judge.

`score.py` homes each reference concept into the DEEPEST parser node whose page
range contains it. Once fragments are sub-page, several fragments of one section
share a page and exactly one of them wins the home; its siblings become nodes no
reference concept describes, and every edge touching them is counted spurious
whether it is right or wrong.

So collapse each fragment onto its outline section -- recoverable from the
structural spine in the graph itself -- and score the result against the same
reference. Same edges, same reference, granularity the reference can express.
If the collapsed segmented graph scores like the unsegmented one, the edge
quality did not degrade and the reported precision is measuring the reference's
resolution rather than the parser's.
"""

import json
import sys

sys.path.insert(0, sys.argv[2])
from score import score  # noqa: E402

graph = json.load(open(sys.argv[1], encoding="utf-8"))

parent = {e["target"]: e["prereq"] for e in graph["edges"] if e["origin"] == "structural"}
by_slug = {n["slug"]: n for n in graph["nodes"]}
outline = {n["slug"] for n in graph["nodes"] if not n.get("is_fragment", False)}


def section_of(slug: str) -> str:
    seen, cur = set(), slug
    while cur not in outline and cur in parent and cur not in seen:
        seen.add(cur)
        cur = parent[cur]
    return cur if cur in outline else slug


collapsed_nodes = {}
for node in graph["nodes"]:
    home = section_of(node["slug"])
    keep = collapsed_nodes.get(home)
    if keep is None:
        collapsed_nodes[home] = dict(by_slug[home]) if home in by_slug else dict(node)

edges = {}
for edge in graph["edges"]:
    a, b = section_of(edge["prereq"]), section_of(edge["target"])
    if a != b:
        best = edges.get((a, b))
        if best is None or edge["confidence"] > best["confidence"]:
            edges[(a, b)] = {"prereq": a, "target": b, "confidence": edge["confidence"], "origin": edge["origin"]}

collapsed = {
    "nodes": list(collapsed_nodes.values()),
    "edges": list(edges.values()),
    "depths": {s: 0 for s in collapsed_nodes},
}
print(f"{len(graph['nodes'])} nodes / {len(graph['edges'])} edges  ->  "
      f"{len(collapsed['nodes'])} sections / {len(collapsed['edges'])} edges")
result = score(collapsed, verbose="--verbose" in sys.argv)
print(json.dumps({k: v for k, v in result.items() if not k.startswith("_")}, indent=1))

if "--verbose" in sys.argv:
    origin = {(e["prereq"], e["target"]): e["origin"] for e in collapsed["edges"]}
    print("\nbackwards:")
    for a, b in result["_backwards"]:
        print(f"  {a:46s} -> {b:46s} {origin[(a, b)]}")
    print("\nspurious (inferred only):")
    for a, b in result["_spurious"]:
        if origin[(a, b)] == "inferred":
            print(f"  {a:46s} -> {b}")
