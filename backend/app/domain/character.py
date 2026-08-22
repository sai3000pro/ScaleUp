"""Pure rules for the learner character layer.

Character identity and perk choices are persisted by the application service, but
all derived presentation values stay here so they remain deterministic and easy
to test without a database.
"""

from __future__ import annotations

from dataclasses import dataclass

ARCHETYPES = ("scholar", "builder", "explorer", "mentor")
AVATARS = ("owl", "fox", "robot", "wizard", "cat", "dragon")
SKIN_TONES = ("moon", "sand", "honey", "copper", "ebony")
HAIR_STYLES = ("sweep", "curls", "bob", "mohawk", "crown")
HAIR_COLORS = ("ink", "chestnut", "silver", "violet", "rose")
OUTFIT_COLORS = ("azure", "violet", "coral", "mint", "gold")
ACCESSORIES = ("none", "glasses", "headband", "crown", "earring")


@dataclass(frozen=True, slots=True)
class PerkDefinition:
    id: str
    title: str
    description: str


PERKS = (
    PerkDefinition("daily_momentum", "Daily Momentum", "Show one extra frontier quest on the Daily Quest board."),
    PerkDefinition("second_wind", "Second Wind", "Gain a resilience bonus for rescuing fading skills."),
    PerkDefinition("cartographer", "Cartographer", "Reveal richer progress context for every course branch."),
    PerkDefinition("deep_focus", "Deep Focus", "Turn a focused drill session into a visible character achievement."),
    PerkDefinition("scholars_eye", "Scholar's Eye", "Highlight source evidence as your strongest learning signal."),
)


@dataclass(frozen=True, slots=True)
class CharacterStats:
    focus: int
    memory: int
    resilience: int
    curiosity: int


# @spec PROG-META-001
def calculate_stats(
    level: int,
    streak_days: int,
    average_score: float,
    started_skills: int,
    mastered_skills: int,
    course_count: int,
    rescue_count: int,
    unlocked_perks: set[str],
) -> CharacterStats:
    """Convert learning behavior into readable RPG stats, capped at 99."""
    perk_bonus = len(unlocked_perks) * 2
    level_bonus = level * 3
    focus = 30 + level * 4 + round(max(0.0, min(1.0, average_score)) * 25) + perk_bonus
    memory = 25 + level_bonus + min(35, mastered_skills * 4) + min(25, started_skills * 2) + perk_bonus
    resilience = 25 + level_bonus + min(30, streak_days * 5) + min(20, rescue_count * 3) + perk_bonus
    curiosity = 30 + level_bonus + min(25, course_count * 5) + min(25, started_skills * 2) + perk_bonus
    return CharacterStats(
        focus=min(99, focus),
        memory=min(99, memory),
        resilience=min(99, resilience),
        curiosity=min(99, curiosity),
    )


def perk_definitions(unlocked_perks: set[str]) -> list[dict[str, object]]:
    """Return a stable catalog suitable for an API response."""
    return [
        {
            "id": perk.id,
            "title": perk.title,
            "description": perk.description,
            "cost": 1,
            "unlocked": perk.id in unlocked_perks,
        }
        for perk in PERKS
    ]


def achievement_rows(
    attempts: int,
    started_skills: int,
    mastered_skills: int,
    streak_days: int,
    rescue_count: int,
    unlocked_perks: int,
) -> list[dict[str, object]]:
    """Build achievements from facts, without creating another event ledger."""
    definitions = (
        ("first_drill", "First Steps", "Complete your first graded drill.", attempts, 1),
        ("skill_seeker", "Skill Seeker", "Start five skills across your courses.", started_skills, 5),
        ("branch_master", "Branch Master", "Master your first skill.", mastered_skills, 1),
        ("streak_starter", "Streak Starter", "Study on three consecutive days.", streak_days, 3),
        ("rescue_ranger", "Rescue Ranger", "Rescue three fading skills.", rescue_count, 3),
        ("perk_collector", "Perk Collector", "Unlock three character perks.", unlocked_perks, 3),
    )
    return [
        {
            "id": achievement_id,
            "title": title,
            "description": description,
            "progress": min(value, target),
            "target": target,
            "unlocked": value >= target,
        }
        for achievement_id, title, description, value, target in definitions
    ]
