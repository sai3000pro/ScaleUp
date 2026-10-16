"""Edge kinds rank in one declared place."""

from app.curricula import planner
from app.ingestion import confidence, prereqs, toc


# @spec CURR-EDGE-007
def test_the_ladder_is_ascending_and_outline_sits_below_inference() -> None:
    assert confidence.ladder_is_ordered()
    values = dict(confidence.CONFIDENCE_LADDER)
    assert values["outline_introduces"] < values["inferred_floor"]
    assert values["inferred_ceiling_single"] < values["inferred_ceiling_agreed"]


# @spec CURR-EDGE-007
def test_every_module_reads_its_threshold_from_the_ladder() -> None:
    assert toc.INTRODUCES_CONFIDENCE is confidence.INTRODUCES_CONFIDENCE
    assert prereqs.MIN_CONFIDENCE is confidence.MIN_CONFIDENCE
    assert prereqs.MAX_AGREED_CONFIDENCE is confidence.MAX_AGREED_CONFIDENCE
    assert planner.CATALOGUE_DEFAULT_CONFIDENCE is confidence.CATALOGUE_DEFAULT_CONFIDENCE


def test_a_descending_ladder_is_rejected() -> None:
    assert not confidence.ladder_is_ordered((("a", 0.9), ("b", 0.5)))
