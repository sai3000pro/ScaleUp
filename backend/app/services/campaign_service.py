"""RPG campaign briefing projections.

This service joins the learner's persisted campaign objective to the generated
skill graph. Outcome coverage is intentionally a lexical signal over skill
names and summaries, not a model confidence score.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMRole
from app.models import Course, CurriculumProposal, SkillEdge, SkillNode
from app.schemas.campaign import (
    CampaignBriefingOut,
    CampaignOutcomeCoverage,
    CampaignOutcomeEvaluationOut,
    CampaignSkillRef,
    CampaignTreeShape,
)
from app.services.llm_gateway import recording_llm_client

logger = logging.getLogger(__name__)

_OUTCOME_STOPWORDS = frozenset(
    "and the for with from into that this learn understand know use a an to of in on".split()
)


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{3,}", text.lower())
    return list(dict.fromkeys(word for word in words if word not in _OUTCOME_STOPWORDS))


def _playable_prerequisites(
    node_id: uuid.UUID,
    prereqs: dict[uuid.UUID, list[uuid.UUID]],
    assessable: dict[uuid.UUID, bool],
) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()
    seen: set[uuid.UUID] = set()

    def walk(current: uuid.UUID) -> None:
        for prereq_id in prereqs.get(current, []):
            if prereq_id in seen:
                pass
            else:
                seen.add(prereq_id)
                if assessable.get(prereq_id, False):
                    found.add(prereq_id)
                else:
                    walk(prereq_id)

    walk(node_id)
    return found


async def build_briefing(session: AsyncSession, course: Course) -> CampaignBriefingOut:
    proposal = await session.scalar(
        select(CurriculumProposal)
        .where(
            CurriculumProposal.course_id == course.id,
            CurriculumProposal.owner_id == course.owner_id,
        )
        .order_by(CurriculumProposal.proposal_version.desc())
        .limit(1)
    )
    nodes = list(await session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)))
    skills = sorted(
        (node for node in nodes if node.assessable),
        key=lambda node: (node.depth, node.title.casefold(), str(node.id)),
    )
    skill_ids = {node.id for node in skills}
    edge_rows = list(
        await session.execute(
            select(SkillEdge.prereq_id, SkillEdge.target_id).where(SkillEdge.course_id == course.id)
        )
    )
    prereqs: dict[uuid.UUID, list[uuid.UUID]] = {}
    for source, target in edge_rows:
        prereqs.setdefault(target, []).append(source)
    assessable = {node.id: node.assessable for node in nodes}
    prerequisite_edges = [
        (source, target)
        for target in skill_ids
        for source in _playable_prerequisites(target, prereqs, assessable)
    ]
    roots = [node for node in skills if not _playable_prerequisites(node.id, prereqs, assessable)]

    depth_counts: dict[str, int] = {}
    for node in skills:
        key = str(node.depth)
        depth_counts[key] = depth_counts.get(key, 0) + 1
    deepest = max((node.depth for node in skills), default=0)
    tree_shape = CampaignTreeShape(
        playable_skills=len(skills),
        branches=len(roots),
        prerequisite_links=len(prerequisite_edges),
        depth=deepest + 1 if skills else 0,
        depth_counts=dict(sorted(depth_counts.items(), key=lambda item: int(item[0]))),
        starting_skills=[CampaignSkillRef(id=node.id, title=node.title) for node in roots[:8]],
    )

    outcome = proposal.target_outcome if proposal is not None else ""
    terms = _terms(outcome)
    graph_words = {
        word
        for node in skills
        for word in _terms(f"{node.title} {node.summary}")
    }
    matched_terms = [term for term in terms if term in graph_words]
    missing_terms = [term for term in terms if term not in graph_words]
    coverage = round(len(matched_terms) / len(terms), 4) if terms else 0.0
    signal = _coverage_signal(terms, matched_terms)

    return CampaignBriefingOut(
        course_id=course.id,
        goal=proposal.goal if proposal is not None else None,
        target_outcome=outcome,
        proposal_version=proposal.proposal_version if proposal is not None else None,
        tree_shape=tree_shape,
        outcome_coverage=CampaignOutcomeCoverage(
            outcome=outcome,
            terms=terms,
            matched_terms=matched_terms,
            missing_terms=missing_terms,
            coverage=coverage,
            signal=signal,
        ),
    )


def _coverage_signal(terms: list[str], matched_terms: list[str]) -> str:
    if not terms:
        return "No victory condition supplied."
    if len(matched_terms) == len(terms):
        return "Every objective term is visible in the generated skill graph."
    if matched_terms:
        return "Some objective terms are visible; review the missing terms before expanding the campaign."
    return "No objective terms are obvious in the generated skill graph yet."


def _fallback_evaluation(outcome: str, skills: list[object]) -> dict[str, object]:
    terms = set(_terms(outcome))
    matched_slugs: list[str] = []
    covered: set[str] = set()
    for node in skills:
        overlap = terms & set(_terms(f"{node.title} {node.summary}"))
        if overlap:
            matched_slugs.append(node.slug)
            covered.update(overlap)
    missing = sorted(terms - covered)
    readiness = round(len(covered) / len(terms), 4) if terms else 0.0
    rationale = (
        "The generated skill summaries cover these objective terms: " + ", ".join(sorted(covered)) + "."
        if covered
        else "The generated skill summaries do not clearly cover the stated objective yet."
    )
    return {
        "matched_skill_slugs": matched_slugs,
        "missing_capabilities": missing,
        "readiness": readiness,
        "rationale": rationale,
    }


async def evaluate_outcome(session: AsyncSession, course: Course) -> CampaignOutcomeEvaluationOut:
    proposal = await session.scalar(
        select(CurriculumProposal)
        .where(
            CurriculumProposal.course_id == course.id,
            CurriculumProposal.owner_id == course.owner_id,
        )
        .order_by(CurriculumProposal.proposal_version.desc())
        .limit(1)
    )
    nodes = list(await session.scalars(select(SkillNode).where(SkillNode.course_id == course.id)))
    skills = sorted(
        (node for node in nodes if node.assessable),
        key=lambda node: (node.depth, node.title.casefold(), str(node.id)),
    )
    outcome = proposal.target_outcome.strip() if proposal is not None else ""
    if not outcome:
        return CampaignOutcomeEvaluationOut(
            course_id=course.id,
            outcome="",
            provider="none",
            mode="unavailable",
            evaluated_skill_count=len(skills),
            readiness=0.0,
            matched_skills=[],
            missing_capabilities=["a victory condition"],
            side_quests=[],
            rationale="Set a victory condition before asking the campaign evaluator to review the tree.",
        )

    if not skills:
        return CampaignOutcomeEvaluationOut(
            course_id=course.id,
            outcome=outcome,
            provider="none",
            mode="unavailable",
            evaluated_skill_count=0,
            readiness=0.0,
            matched_skills=[],
            missing_capabilities=["generated skills"],
            side_quests=[],
            rationale="The skill tree is still empty, so there is no generated campaign to evaluate yet.",
        )

    evaluated_skills = skills[:80]
    listing = "\n".join(
        f"- {node.slug} | {node.title} | {node.summary[:240]}" for node in evaluated_skills
    )
    provider = "unavailable"
    mode = "lexical_fallback"
    data = _fallback_evaluation(outcome, evaluated_skills)
    try:
        client = recording_llm_client(course.id)
        provider = client.provider
        result = await client.structured(
            LLMRole.CAMPAIGN_OUTCOME_EVAL,
            {"outcome": outcome, "skills": listing},
            course_id=str(course.id),
        )
        data = result.data
        mode = "deterministic" if provider == "fake" else "semantic"
    except Exception as exc:  # noqa: BLE001 - the fallback keeps the campaign usable during provider outages
        logger.warning("campaign outcome evaluation fell back to lexical coverage: %s", exc)

    by_slug = {node.slug: node for node in evaluated_skills}
    matched_slugs = list(dict.fromkeys(slug for slug in data.get("matched_skill_slugs", []) if slug in by_slug))
    matched_skills = [CampaignSkillRef(id=by_slug[slug].id, title=by_slug[slug].title) for slug in matched_slugs]
    missing = list(
        dict.fromkeys(str(item).strip()[:120] for item in data.get("missing_capabilities", []) if str(item).strip())
    )[:12]
    readiness = max(0.0, min(1.0, float(data.get("readiness", 0.0))))
    rationale = str(data.get("rationale", "The evaluator returned no rationale."))[:600]
    return CampaignOutcomeEvaluationOut(
        course_id=course.id,
        outcome=outcome,
        provider=provider,
        mode=mode,
        evaluated_skill_count=len(evaluated_skills),
        readiness=readiness,
        matched_skills=matched_skills,
        missing_capabilities=missing,
        side_quests=_side_quests(outcome, missing),
        rationale=rationale,
    )


def _side_quests(outcome: str, missing_capabilities: list[str]) -> list[dict[str, str]]:
    """Turn evaluator gaps into source-addition work, never pretend they are skills.

    A missing capability has no node id and therefore cannot be drilled or
    awarded EXP. The returned quest is an explicit research prompt that the
    learner can use to create a new, reviewable proposal.
    """
    quests: list[dict[str, str]] = []
    for capability in missing_capabilities:
        clean = " ".join(capability.split())[:120]
        if clean:
            quests.append(
                {
                    "capability": clean,
                    "title": f"Find evidence for {clean}",
                    "reason": f'The generated tree does not clearly cover "{clean}" for this victory condition.',
                    "source_query": f"{outcome}; focus on {clean}; include practical examples and assessment material",
                    "action": "Find and approve a source focused on this capability, then ingest it to grow the campaign tree.",
                }
            )
    return quests
