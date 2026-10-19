"""Outline entries are filtered by title distinctiveness before segmentation."""

from app.ingestion.toc import TocNode, distinctive_entries


def _node(slug: str, title: str) -> TocNode:
    return TocNode(slug=slug, title=title, level=1, page_start=1, page_end=2, parent_slug=None, has_children=False)


# @spec CURR-PARSE-007
def test_generic_and_duplicated_titles_are_held_back_from_segmentation() -> None:
    nodes = [
        _node("intro", "Introduction"),
        _node("lp", "Linear Programming"),
        _node("ex-1", "Exercises"),
        _node("dual", "Duality"),
        _node("dual-2", "Duality"),
    ]
    kept, dropped = distinctive_entries(nodes)
    assert [node.slug for node in kept] == ["lp"]
    assert [node.slug for node in dropped] == ["intro", "ex-1", "dual", "dual-2"]
