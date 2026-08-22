"""EXP awards and level curves.

Pure. The client never computes any of this -- it displays what the server
awarded. See docs/srs_and_exp.md.
"""

from __future__ import annotations

__all__ = [
    "DIFFICULTY_MULT",
    "NODE_LEVEL_CAP",
    "FIRST_PASS_BONUS",
    "rescue_multiplier",
    "award_for_attempt",
    "exp_for_node_level",
    "node_level_for_exp",
    "account_level_for_exp",
    "level_progress",
]

DIFFICULTY_MULT: dict[int, float] = {1: 0.7, 2: 0.85, 3: 1.0, 4: 1.2, 5: 1.4}
NODE_LEVEL_CAP = 5
FIRST_PASS_BONUS = 50
BASE_AWARD = 100
MAX_RESCUE_MULTIPLIER = 1.5


# @spec PROG-EXP-005
def rescue_multiplier(overdue_days: float, interval_days: float) -> float:
    """Up to 1.5x for rescuing a decayed node, scaled by how far gone it is.

    This is the mechanic that makes the Daily Quest board worth clearing. Without
    it, review competes with new content and rationally loses -- which defeats
    the entire point of a retention system.
    """
    if overdue_days <= 0.0:
        return 1.0
    fraction = min(1.0, overdue_days / max(interval_days, 0.5))
    return 1.0 + (MAX_RESCUE_MULTIPLIER - 1.0) * fraction


# @spec PROG-EXP-001, PROG-EXP-005
def award_for_attempt(
    score: float,
    difficulty: int,
    overdue_days: float = 0.0,
    interval_days: float = 0.0,
    is_first_pass: bool = False,
) -> int:
    """EXP for a single graded attempt."""
    clamped = max(0.0, min(1.0, score))
    multiplier = DIFFICULTY_MULT.get(difficulty, 1.0)
    rescue = rescue_multiplier(overdue_days, interval_days)
    base = round(BASE_AWARD * clamped * multiplier * rescue)
    bonus = FIRST_PASS_BONUS if is_first_pass else 0
    return int(base + bonus)


def exp_for_node_level(level: int) -> int:
    """Cumulative EXP needed to reach a node level. 0, 100, 303, 623, 1057."""
    if level <= 0:
        return 0
    return round(100 * level**1.6)


# @spec PROG-EXP-003, PROG-EXP-004, PROG-EXP-006
def node_level_for_exp(exp: int) -> int:
    """Highest node level fully paid for by `exp`, capped at NODE_LEVEL_CAP."""
    level = 0
    while level < NODE_LEVEL_CAP and exp >= exp_for_node_level(level + 1):
        level += 1
    return level


# @spec PROG-EXP-003
def account_level_for_exp(total_exp: int) -> int:
    """Same curve at 10x scale, uncapped."""
    level = 0
    while total_exp >= round(1000 * (level + 1) ** 1.6):
        level += 1
    return level


def level_progress(total_exp: int) -> tuple[int, int, int]:
    """Return (level, exp_into_level, exp_for_next_level) for the account curve."""
    level = account_level_for_exp(total_exp)
    floor_exp = 0 if level == 0 else round(1000 * level**1.6)
    ceiling_exp = round(1000 * (level + 1) ** 1.6)
    return level, total_exp - floor_exp, ceiling_exp - floor_exp
