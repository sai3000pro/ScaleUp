"""The skill list is written by `prereqs` and read back by the fake provider.

Those two live in different layers and nothing type-checks the format between
them, so a title that survived rendering but not parsing produced no error --
just a node silently matching on a prefix of its own name, and edges nobody
could explain. These tests are the contract.
"""

from __future__ import annotations

from app.ingestion.prereqs import SkillRef, _render_skill_list
from app.llm.fake_provider import _parse_skill_list


def round_trip(*skills: SkillRef) -> dict[str, str]:
    return {slug: title for slug, title, _ in _parse_skill_list(_render_skill_list(list(skills)))}


def test_a_plain_title_survives() -> None:
    assert round_trip(SkillRef("basis", "Basis", "An invertible column submatrix.")) == {"basis": "Basis"}


def test_a_title_containing_a_colon_is_not_truncated() -> None:
    """`toc.py` qualifies generic sections as "Formulations: Overview".

    Parsed up to the first colon, that became "Formulations" -- a word every
    section of the chapter contains -- and the node collected an edge from
    every one of them.
    """
    parsed = round_trip(SkillRef("overview", "Formulations: Overview", "What optimisation is."))
    assert parsed == {"overview": "Formulations: Overview"}


def test_a_summary_containing_a_colon_does_not_eat_the_title() -> None:
    parsed = round_trip(SkillRef("basis", "Basis", "Definition: B is a basis if A_B is invertible."))
    assert parsed == {"basis": "Basis"}


def test_every_skill_round_trips_when_many_are_rendered() -> None:
    skills = [
        SkillRef("a", "Matrix product", "Row by column."),
        SkillRef("b", "Duality: Overview", "Bounds from the other side."),
        SkillRef("c", "The KKT Theorem", "Optimality for convex NLPs."),
    ]
    assert round_trip(*skills) == {"a": "Matrix product", "b": "Duality: Overview", "c": "The KKT Theorem"}
