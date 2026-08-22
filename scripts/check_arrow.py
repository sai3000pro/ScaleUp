r"""Does the arrow of intent actually reach the code?

The design docs and the EARS specs are prose, and prose cannot be wrong in a way
that fails a build. The one mechanical link between intent and code is the
`@spec` annotation, so this checks that link in both directions:

    python scripts\check_arrow.py            # summary, exits non-zero on a broken pointer
    python scripts\check_arrow.py --coverage # which specs nothing cites, by segment
    python scripts\check_arrow.py --segment evaluation

Four checks, matching the structural half of LID's coherence verification:

  1. Every `@spec` annotation names a spec ID that exists.  (hard failure)
  2. Every arrow-index segment has a design doc and a spec file.  (hard failure)
  3. Every spec ID is unique across the whole tree.  (hard failure)
  4. Implemented specs -- `[x]` -- are cited, and separately, are cited by a
     TEST.  (both reported, neither a failure: an unannotated spec is a gap in
     linkage, not a defect in the code, and treating it as a build break would
     make the honest move -- writing a spec for behaviour that already exists --
     feel like a regression.)

Citation and verification are different things, and conflating them is the easier
mistake to make. A `@spec` on the function implementing a behaviour says where
that behaviour lives; only a `@spec` on a test says something checks it. A segment
can reach full citation coverage while a whole facet goes unverified, so the two
numbers are reported separately, and the second is the one that means "guarded".

Two kinds of spec are excluded from coverage, for opposite reasons. A deliberate
non-want (`[D]`) says the system shall NOT do something, so the absence is the
implementation and there is nothing to annotate. An active gap (`[ ]`) has no
implementation yet, so nothing can cite it truthfully -- though a partial one
often can, pointing at where the behaviour diverges. Gaps are counted and shown
separately rather than folded into the score.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTENT = ROOT / "docs" / "intent"

SPEC_LINE = re.compile(r"^-\s*\[([x D])\]\s*\*\*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\*\*", re.MULTILINE)
SPEC_ID = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+-\d{3})\b")
ANNOTATION = re.compile(r"@spec\s+([A-Za-z0-9,\-\s]+)")

SEARCH_ROOTS = (
    ROOT / "backend" / "app",
    ROOT / "backend" / "tests",
    ROOT / "backend" / "alembic",
    ROOT / ".github" / "workflows",
    ROOT / "frontend" / "app",
    ROOT / "frontend" / "components",
    ROOT / "frontend" / "lib",
    ROOT / "frontend" / "stores",
    # Committed build scripts whose output ships. `frontend/scripts` holds the
    # sprite pipeline, which is real implementation of real specs -- leaving it
    # out made sixteen implemented specs read as uncited.
    ROOT / "frontend" / "scripts",
    ROOT / "scripts",
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".js", ".yml", ".yaml"}
SKIP_DIRS = {"node_modules", ".next", "__pycache__", ".venv", "dist", "build"}


class Spec:
    __slots__ = ("id", "status", "segment", "file")

    def __init__(self, spec_id: str, status: str, segment: str, file: Path) -> None:
        self.id = spec_id
        self.status = status
        self.segment = segment
        self.file = file

    @property
    def implemented(self) -> bool:
        """Only `[x]` specs describe behaviour that exists to be pointed at."""
        return self.status == "x"

    @property
    def gap(self) -> bool:
        return self.status == " "


def load_specs() -> tuple[dict[str, Spec], list[str]]:
    """Every spec in the tree, plus any duplicate-ID complaints."""
    specs: dict[str, Spec] = {}
    duplicates: list[str] = []
    for spec_file in sorted(INTENT.glob("*/*-specs.md")):
        segment = spec_file.parent.name
        text = spec_file.read_text(encoding="utf-8")
        for status, spec_id in SPEC_LINE.findall(text):
            if spec_id in specs:
                duplicates.append(f"{spec_id} declared in both {specs[spec_id].segment} and {segment}")
            else:
                specs[spec_id] = Spec(spec_id, status.strip() or " ", segment, spec_file)
    return specs, duplicates


def source_files() -> list[Path]:
    found: list[Path] = []
    for root in SEARCH_ROOTS:
        if root.exists():
            for path in root.rglob("*"):
                if path.suffix in SOURCE_SUFFIXES and not (set(path.parts) & SKIP_DIRS):
                    found.append(path)
    return found


def is_test(path: Path) -> bool:
    return "test" in path.name or "tests" in path.parts


def load_citations() -> tuple[dict[str, list[Path]], set[str], list[tuple[Path, str]]]:
    """spec id -> files citing it, the subset cited by a test, and every raw citation."""
    cited: dict[str, list[Path]] = defaultdict(list)
    verified: set[str] = set()
    raw: list[tuple[Path, str]] = []
    for path in source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            text = ""
        for block in ANNOTATION.findall(text):
            for spec_id in SPEC_ID.findall(block):
                cited[spec_id].append(path)
                raw.append((path, spec_id))
                if is_test(path):
                    verified.add(spec_id)
    return cited, verified, raw


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--coverage", action="store_true", help="list the specs nothing cites")
    parser.add_argument("--untested", action="store_true", help="list implemented specs no test cites")
    parser.add_argument("--segment", help="restrict coverage output to one segment")
    args = parser.parse_args()

    specs, duplicates = load_specs()
    cited, verified, raw = load_citations()

    failures: list[str] = []

    # Check 3 -- uniqueness. Reported first because a duplicate makes every
    # other answer ambiguous.
    failures.extend(duplicates)

    # Check 2 -- each segment folder is complete.
    for spec_file in sorted(INTENT.glob("*/*-specs.md")):
        segment = spec_file.parent.name
        if not (spec_file.parent / f"{segment}-design.md").exists():
            failures.append(f"{segment} has specs but no design doc")

    # Check 1 -- no citation points at a spec that does not exist.
    for path, spec_id in raw:
        if spec_id not in specs:
            failures.append(f"{rel(path)} cites {spec_id}, which no spec file declares")

    implemented = [s for s in specs.values() if s.implemented]
    gaps = [s for s in specs.values() if s.gap]
    covered = [s for s in implemented if s.id in cited]

    by_segment: dict[str, list[Spec]] = defaultdict(list)
    for spec in implemented:
        by_segment[spec.segment].append(spec)
    gaps_by_segment: dict[str, int] = defaultdict(int)
    for spec in gaps:
        gaps_by_segment[spec.segment] += 1

    segment_count = len({spec.segment for spec in specs.values()})
    print(f"{len(specs)} specs across {segment_count} segments: {len(implemented)} implemented, "
          f"{len(gaps)} active gaps, {len(specs) - len(implemented) - len(gaps)} deliberate non-wants")
    guarded = [s for s in implemented if s.id in verified]
    print(f"{len(covered)} of {len(implemented)} implemented specs are cited "
          f"({100 * len(covered) // max(len(implemented), 1)}%)")
    print(f"{len(guarded)} of {len(implemented)} are cited by a TEST "
          f"({100 * len(guarded) // max(len(implemented), 1)}%) -- the number that means guarded\n")

    width = max(len(name) for name in by_segment) if by_segment else 0
    for segment in sorted(by_segment):
        entries = by_segment[segment]
        hit = sum(1 for spec in entries if spec.id in cited)
        tested = sum(1 for spec in entries if spec.id in verified)
        bar = "#" * round(20 * tested / len(entries))
        print(f"  {segment:<{width}}  {hit:>3}/{len(entries):<3} cited  "
              f"{tested:>3}/{len(entries):<3} tested  {bar:<20}  {gaps_by_segment[segment]} gap(s)")

    if args.coverage:
        for segment in sorted(by_segment):
            if args.segment is not None and segment != args.segment:
                pass
            else:
                missing = [spec.id for spec in by_segment[segment] if spec.id not in cited]
                if missing:
                    print(f"\n{segment} -- {len(missing)} uncited:")
                    for spec_id in missing:
                        print(f"  {spec_id}")

    if args.untested:
        for segment in sorted(by_segment):
            if args.segment is None or segment == args.segment:
                missing = [spec.id for spec in by_segment[segment] if spec.id not in verified]
                if missing:
                    print(f"\n{segment} -- {len(missing)} implemented but untested:")
                    for spec_id in missing:
                        print(f"  {spec_id}")

    if failures:
        print(f"\n{len(failures)} structural failure(s):")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print("\nStructural checks pass: every citation resolves, every segment is complete, "
          "every spec ID is unique.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
