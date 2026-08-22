from app.research.providers import ResearchResult
from app.research.ranking import rank_sources, select_diverse_sources
from app.schemas.curriculum import CurriculumProposalCreate
from app.services.curriculum_service import _discovery_queries, _search_query


def _result(title: str, domain: str, snippet: str = "A useful explanation of vectors and their applications.") -> ResearchResult:
    return ResearchResult(
        title=title,
        url=f"https://{domain}/vectors",
        snippet=snippet,
        published_at="2026-08-01",
        domain=domain,
    )


def test_education_domain_and_goal_match_rank_above_placeholder_source() -> None:
    ranked = rank_sources(
        "linear algebra",
        "beginner",
        "textbook",
        [
            _result("Linear algebra textbook fundamentals", "open.example.edu", "A" * 140),
            _result("A guide", "example.com", "A short page."),
        ],
    )

    assert ranked[0].result.domain == "open.example.edu"
    assert ranked[0].score > ranked[1].score
    assert "education domain" in ranked[0].reasons
    assert any("placeholder" in reason for reason in ranked[1].reasons)


def test_ranking_is_deterministic_and_exposes_preference_reason() -> None:
    result = _result("Advanced research paper on vectors", "journals.org")

    ranked = rank_sources(
        "vectors",
        "advanced",
        "papers",
        [result],
        prior_knowledge="vectors",
        application_context="research implementation",
    )

    assert ranked == rank_sources(
        "vectors",
        "advanced",
        "papers",
        [result],
        prior_knowledge="vectors",
        application_context="research implementation",
    )
    assert any("fits advanced / papers preference" in reason for reason in ranked[0].reasons)
    assert any("learner-context" in reason for reason in ranked[0].reasons)


def test_diversification_puts_distinct_domains_in_the_selected_set() -> None:
    ranked = rank_sources(
        "vectors",
        "beginner",
        "mixed",
        [
            _result("Top one", "same.org"),
            _result("Top two", "same.org"),
            _result("Different host", "other.edu"),
        ],
    )

    selected = select_diverse_sources(ranked, 2)

    assert [item.result.domain for item in selected] == ["other.edu", "same.org"]
    assert "adds a distinct source domain" in selected[0].reasons


def test_discovery_queries_are_bounded_and_cover_three_angles() -> None:
    payload = CurriculumProposalCreate(goal="reinforcement learning")

    queries = _discovery_queries(payload)

    assert len(queries) == 4
    assert queries[0].startswith("reinforcement learning for a beginner")
    assert any("practical project" in query for query in queries)
    assert any("reference handbook" in query for query in queries)


def test_search_query_carries_the_campaign_victory_condition() -> None:
    query = _search_query(
        CurriculumProposalCreate(
            goal="reinforcement learning",
            target_outcome="build a robot navigation policy",
        )
    )

    assert "victory condition: build a robot navigation policy" in query


def test_search_query_carries_prior_knowledge_and_application_context() -> None:
    query = _search_query(
        CurriculumProposalCreate(
            goal="reinforcement learning",
            prior_knowledge="Python and linear algebra",
            application_context="robot navigation project",
        )
    )

    assert "prior knowledge: Python and linear algebra" in query
    assert "intended application: robot navigation project" in query
