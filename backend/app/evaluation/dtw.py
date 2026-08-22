"""Small, deterministic Dynamic Time Warping implementation.

The scorer needs the alignment path, not just a distance: missing and extra notes
are learner-facing feedback. This implementation keeps those operations explicit
so the same result is available on Windows, in tests, and in a Render worker.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import inf


@dataclass(frozen=True, slots=True)
class AlignmentStep:
    """One operation in an alignment path."""

    operation: str  # match | delete_expected | insert_observed
    expected_index: int | None
    observed_index: int | None
    cost: float


@dataclass(frozen=True, slots=True)
class DTWAlignment:
    distance: float
    steps: tuple[AlignmentStep, ...]

    @property
    def matches(self) -> tuple[AlignmentStep, ...]:
        return tuple(step for step in self.steps if step.operation == "match")

    @property
    def deletions(self) -> tuple[AlignmentStep, ...]:
        return tuple(step for step in self.steps if step.operation == "delete_expected")

    @property
    def insertions(self) -> tuple[AlignmentStep, ...]:
        return tuple(step for step in self.steps if step.operation == "insert_observed")


# @spec EVAL-ALIGN-001, EVAL-ALIGN-002
def align(
    expected: Sequence[object],
    observed: Sequence[object],
    distance: Callable[[object, object], float],
    deletion_cost: float = 1.0,
    insertion_cost: float = 1.0,
) -> DTWAlignment:
    """Align two sequences and return a deterministic path.

    ``delete_expected`` represents a missed note and ``insert_observed`` an extra
    note. Ties prefer a match, then a deletion, then an insertion, which keeps
    repeated-note cases stable and makes the path easy to explain.
    """
    if deletion_cost < 0 or insertion_cost < 0:
        raise ValueError("DTW gap costs must be non-negative.")

    expected_count = len(expected)
    observed_count = len(observed)
    costs = [[inf] * (observed_count + 1) for _ in range(expected_count + 1)]
    choices: list[list[str | None]] = [
        [None] * (observed_count + 1) for _ in range(expected_count + 1)
    ]
    costs[0][0] = 0.0

    for expected_index in range(1, expected_count + 1):
        costs[expected_index][0] = costs[expected_index - 1][0] + deletion_cost
        choices[expected_index][0] = "delete_expected"
    for observed_index in range(1, observed_count + 1):
        costs[0][observed_index] = costs[0][observed_index - 1] + insertion_cost
        choices[0][observed_index] = "insert_observed"

    for expected_index in range(1, expected_count + 1):
        for observed_index in range(1, observed_count + 1):
            match_cost = costs[expected_index - 1][observed_index - 1] + distance(
                expected[expected_index - 1], observed[observed_index - 1]
            )
            delete_cost = costs[expected_index - 1][observed_index] + deletion_cost
            insert_cost = costs[expected_index][observed_index - 1] + insertion_cost
            best_cost = match_cost
            best_choice = "match"
            if delete_cost < best_cost:
                best_cost = delete_cost
                best_choice = "delete_expected"
            if insert_cost < best_cost:
                best_cost = insert_cost
                best_choice = "insert_observed"
            costs[expected_index][observed_index] = best_cost
            choices[expected_index][observed_index] = best_choice

    steps: list[AlignmentStep] = []
    expected_index = expected_count
    observed_index = observed_count
    while expected_index > 0 or observed_index > 0:
        choice = choices[expected_index][observed_index]
        if choice == "match":
            left = expected[expected_index - 1]
            right = observed[observed_index - 1]
            steps.append(
                AlignmentStep(
                    operation=choice,
                    expected_index=expected_index - 1,
                    observed_index=observed_index - 1,
                    cost=distance(left, right),
                )
            )
            expected_index -= 1
            observed_index -= 1
        elif choice == "delete_expected":
            steps.append(
                AlignmentStep(
                    operation=choice,
                    expected_index=expected_index - 1,
                    observed_index=None,
                    cost=deletion_cost,
                )
            )
            expected_index -= 1
        elif choice == "insert_observed":
            steps.append(
                AlignmentStep(
                    operation=choice,
                    expected_index=None,
                    observed_index=observed_index - 1,
                    cost=insertion_cost,
                )
            )
            observed_index -= 1
        else:
            raise RuntimeError("DTW backtracking reached an unset choice.")

    steps.reverse()
    return DTWAlignment(distance=costs[expected_count][observed_count], steps=tuple(steps))
