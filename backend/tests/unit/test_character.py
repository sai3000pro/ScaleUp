from app.domain.character import achievement_rows, calculate_stats, perk_definitions


def test_stats_are_deterministic_and_capped() -> None:
    stats = calculate_stats(
        level=20,
        streak_days=20,
        average_score=1.0,
        started_skills=50,
        mastered_skills=50,
        course_count=50,
        rescue_count=50,
        unlocked_perks={"daily_momentum", "second_wind"},
    )

    assert stats.focus == 99
    assert stats.memory == 99
    assert stats.resilience == 99
    assert stats.curiosity == 99


def test_perk_catalog_marks_only_persisted_choices_unlocked() -> None:
    perks = perk_definitions({"cartographer"})

    cartographer = next(perk for perk in perks if perk["id"] == "cartographer")
    daily_momentum = next(perk for perk in perks if perk["id"] == "daily_momentum")
    assert cartographer["unlocked"] is True
    assert daily_momentum["unlocked"] is False
    assert all(perk["cost"] == 1 for perk in perks)


def test_achievements_clamp_progress_and_unlock_at_target() -> None:
    achievements = achievement_rows(
        attempts=4,
        started_skills=2,
        mastered_skills=1,
        streak_days=3,
        rescue_count=10,
        unlocked_perks=0,
    )

    first = next(achievement for achievement in achievements if achievement["id"] == "first_drill")
    seeker = next(achievement for achievement in achievements if achievement["id"] == "skill_seeker")
    rescue = next(achievement for achievement in achievements if achievement["id"] == "rescue_ranger")
    assert first["unlocked"] is True
    assert seeker["progress"] == 2
    assert seeker["unlocked"] is False
    assert rescue["progress"] == 3
    assert rescue["unlocked"] is True
