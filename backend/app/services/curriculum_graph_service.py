"""The only service allowed to publish a curriculum graph.

Draft candidates are inert. They become learner-facing only after every candidate
has an explicit review decision and publication projects the immutable version
through the existing DAG persistence choke point.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased

from app.domain.dag import CandidateEdge, RejectedEdge, build_acyclic_edges
from app.models import (
    Chunk,
    Course,
    CurriculumEvidence,
    CurriculumNode,
    CurriculumReview,
    CurriculumVersion,
    Instrument,
    PrerequisiteCandidate,
    SkillDefinition,
    SkillNode,
)
from app.schemas.curriculum import CurriculumCandidateOut, CurriculumPublishOut, CurriculumVersionCreate, CurriculumVersionOut
from app.services import score_service
from app.services.graph_service import ConceptSpec, persist_graph

CURRICULUM_COMPILER_VERSION = "curriculum-compiler-v1"


@dataclass(frozen=True, slots=True)
class EvidenceSpec:
    chunk_id: uuid.UUID
    quote: str
    extractor_version: str = CURRICULUM_COMPILER_VERSION
    prompt_sha256: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CurriculumWriteResult:
    version_id: uuid.UUID
    version: int
    status: str
    node_count: int
    candidate_count: int
    rejected_count: int


@dataclass(frozen=True, slots=True)
class CurriculumPublishResult:
    version_id: uuid.UUID
    graph_version: int
    node_count: int
    edge_count: int
    rendered_edge_count: int = 0
    max_depth: int = 0


def _flat(text: str) -> str:
    return " ".join(text.split()).casefold()


def _source_bundle_hash(session: Session, course_id: uuid.UUID, chunk_ids: set[uuid.UUID]) -> str | None:
    if not chunk_ids:
        return None
    chunks = list(session.scalars(select(Chunk).where(Chunk.course_id == course_id, Chunk.id.in_(chunk_ids))))
    if len(chunks) != len(chunk_ids):
        raise ValueError("Every curriculum source chunk must belong to the course.")
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda item: str(item.id)):
        digest.update(str(chunk.id).encode("ascii"))
        digest.update(chunk.content_sha256.encode("ascii"))
    return digest.hexdigest()


def _get_or_create_instrument(session: Session, slug: str, title: str) -> Instrument:
    instrument = session.scalar(select(Instrument).where(Instrument.slug == slug))
    if instrument is None:
        instrument = Instrument(slug=slug, title=title)
        session.add(instrument)
        session.flush()
    return instrument


def _get_or_create_skill(
    session: Session,
    instrument_id: uuid.UUID,
    concept: ConceptSpec,
) -> SkillDefinition:
    definition = session.scalar(
        select(SkillDefinition).where(
            SkillDefinition.instrument_id == instrument_id,
            SkillDefinition.slug == concept.slug,
        )
    )
    if definition is None:
        definition = SkillDefinition(
            instrument_id=instrument_id,
            slug=concept.slug,
            title=concept.title,
            summary=concept.summary,
            aliases=[],
            difficulty=concept.difficulty or 3,
            assessable=concept.assessable,
        )
        session.add(definition)
        session.flush()
    return definition


def _unique_candidates(candidates: Sequence[CandidateEdge]) -> list[CandidateEdge]:
    """Collapse repeated extractor proposals before the DB unique constraint."""
    unique: dict[tuple[str, str], CandidateEdge] = {}
    for candidate in candidates:
        pair = (candidate.prereq, candidate.target)
        previous = unique.get(pair)
        if previous is None:
            unique[pair] = candidate
        else:
            unique[pair] = CandidateEdge(
                prereq=candidate.prereq,
                target=candidate.target,
                confidence=max(previous.confidence, candidate.confidence),
                support=previous.support + candidate.support,
                rationale=previous.rationale or candidate.rationale,
            )
    return list(unique.values())


def _validate_evidence(
    session: Session,
    course: Course,
    evidence_by_edge: Mapping[tuple[str, str], Sequence[EvidenceSpec]],
) -> dict[tuple[str, str], list[EvidenceSpec]]:
    all_specs = [spec for specs in evidence_by_edge.values() for spec in specs]
    chunk_ids = {spec.chunk_id for spec in all_specs}
    chunks = {}
    if chunk_ids:
        chunks = {
            chunk.id: chunk
            for chunk in session.scalars(select(Chunk).where(Chunk.course_id == course.id, Chunk.id.in_(chunk_ids)))
        }
    if len(chunks) != len(chunk_ids):
        raise ValueError("Curriculum evidence references a chunk outside the course.")

    validated: dict[tuple[str, str], list[EvidenceSpec]] = {}
    for pair, specs in evidence_by_edge.items():
        checked: list[EvidenceSpec] = []
        for spec in specs:
            chunk = chunks[spec.chunk_id]
            quote = " ".join(spec.quote.split())
            if not quote or _flat(quote) not in _flat(chunk.text):
                raise ValueError(f"Evidence quote for {pair[0]} -> {pair[1]} is not present in its chunk.")
            if spec.source_sha256 is not None and spec.source_sha256 != chunk.content_sha256:
                raise ValueError(f"Evidence hash for chunk {spec.chunk_id} does not match the stored chunk.")
            checked.append(
                EvidenceSpec(
                    chunk_id=spec.chunk_id,
                    quote=quote,
                    extractor_version=spec.extractor_version,
                    prompt_sha256=spec.prompt_sha256,
                    source_sha256=chunk.content_sha256,
                )
            )
        validated[pair] = checked
    return validated


# @spec CURR-VERSION-002, CURR-VERSION-003
def create_draft(
    session: Session,
    course: Course,
    instrument_slug: str,
    instrument_title: str,
    curriculum_slug: str,
    title: str,
    concepts: Sequence[ConceptSpec],
    candidates: Sequence[CandidateEdge],
    evidence_by_edge: Mapping[tuple[str, str], Sequence[EvidenceSpec]] | None = None,
    source_bundle_sha256: str | None = None,
    compiler_version: str = CURRICULUM_COMPILER_VERSION,
) -> CurriculumWriteResult:
    """Persist a safe, reviewable draft without touching ``skill_nodes``."""
    if not concepts:
        raise ValueError("A curriculum must contain at least one concept.")
    evidence = _validate_evidence(session, course, evidence_by_edge or {})
    instrument = _get_or_create_instrument(session, instrument_slug, instrument_title)
    latest = session.scalar(
        select(CurriculumVersion)
        .where(CurriculumVersion.course_id == course.id, CurriculumVersion.slug == curriculum_slug)
        .order_by(CurriculumVersion.version.desc())
        .limit(1)
    )
    version = CurriculumVersion(
        course_id=course.id,
        instrument_id=instrument.id,
        slug=curriculum_slug,
        title=title,
        version=(latest.version + 1) if latest is not None else 1,
        status="draft",
        compiler_version=compiler_version,
        source_bundle_sha256=source_bundle_sha256,
        supersedes_id=latest.id if latest is not None else None,
    )
    session.add(version)
    session.flush()

    definitions = {
        concept.slug: _get_or_create_skill(session, instrument.id, concept)
        for concept in concepts
    }
    source_ids = {
        chunk_id
        for concept in concepts
        for chunk_id in concept.source_chunk_ids
    }
    computed_hash = _source_bundle_hash(session, course.id, source_ids)
    if version.source_bundle_sha256 is None:
        version.source_bundle_sha256 = computed_hash

    for position, concept in enumerate(concepts):
        session.add(
            CurriculumNode(
                curriculum_version_id=version.id,
                skill_definition_id=definitions[concept.slug].id,
                position=position,
                section=concept.section,
                source_chunk_ids=list(concept.source_chunk_ids),
                assessment_capability={"assessable": concept.assessable},
            )
        )
    session.flush()

    unique_candidates = _unique_candidates(candidates)
    slug_set = set(definitions)
    unknown = [
        candidate
        for candidate in unique_candidates
        if candidate.prereq not in slug_set or candidate.target not in slug_set
    ]
    if unknown:
        raise ValueError("Curriculum candidates must reference concepts in the same version.")
    accepted, rejected = build_acyclic_edges(slug_set, unique_candidates)
    rejected_by_pair = {(item.prereq, item.target): item for item in rejected}
    for candidate in accepted:
        row = PrerequisiteCandidate(
            curriculum_version_id=version.id,
            prereq_skill_id=definitions[candidate.prereq].id,
            target_skill_id=definitions[candidate.target].id,
            confidence=candidate.confidence,
            support=candidate.support,
            rationale=candidate.rationale or None,
            status="draft",
        )
        session.add(row)
        session.flush()
        for spec in evidence.get((candidate.prereq, candidate.target), []):
            session.add(
                CurriculumEvidence(
                    candidate_id=row.id,
                    chunk_id=spec.chunk_id,
                    quote=spec.quote,
                    extractor_version=spec.extractor_version,
                    prompt_sha256=spec.prompt_sha256,
                    source_sha256=spec.source_sha256 or "",
                )
            )

    for candidate in rejected:
        row = PrerequisiteCandidate(
            curriculum_version_id=version.id,
            prereq_skill_id=definitions[candidate.prereq].id,
            target_skill_id=definitions[candidate.target].id,
            confidence=candidate.confidence,
            support=candidate.support,
            rationale=candidate.rationale or None,
            status="rejected",
            rejection_reason=candidate.reason,
            cycle_path=list(candidate.cycle_path),
        )
        session.add(row)

    version.status = "review" if accepted else "draft"
    session.flush()
    return CurriculumWriteResult(
        version_id=version.id,
        version=version.version,
        status=version.status,
        node_count=len(concepts),
        candidate_count=len(accepted),
        rejected_count=len(rejected_by_pair),
    )


# @spec CURR-VERSION-004, CURR-VERSION-008
# @spec CURR-GOAL-017
def review_candidate(
    session: Session,
    version_id: uuid.UUID,
    candidate_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    decision: str,
    reason: str = "",
) -> PrerequisiteCandidate:
    """Record an explicit review; accepting requires grounded evidence."""
    if decision not in {"accepted", "rejected", "ambiguous"}:
        raise ValueError("Invalid curriculum review decision.")
    version = session.get(CurriculumVersion, version_id)
    candidate = session.get(PrerequisiteCandidate, candidate_id)
    if version is None or candidate is None or candidate.curriculum_version_id != version_id:
        raise LookupError("Curriculum candidate not found.")
    if version.status in {"published", "retired"}:
        raise ValueError("Published curriculum versions are immutable.")
    evidence_count = session.scalar(
        select(func.count(CurriculumEvidence.id)).where(CurriculumEvidence.candidate_id == candidate.id)
    )
    # An accepted edge must be justifiable, because an unreviewable graph cannot
    # be trusted or corrected. What counts as justification depends on where the
    # edge came from: an edge inferred from a document owes an exact quote from
    # it, while an edge drawn from the shared catalogue or proposed against it
    # never read a document and owes a recorded rationale instead. Demanding a
    # source quote from a tree built without sources would require quoting a book
    # nobody opened.
    if decision == "accepted" and not evidence_count and not (candidate.rationale or "").strip():
        raise ValueError(
            "An accepted prerequisite must carry a justification: an evidence quote where it was "
            "derived from a document, or a recorded rationale where it was not."
        )
    candidate.status = decision
    session.add(
        CurriculumReview(
            candidate_id=candidate.id,
            reviewer_id=reviewer_id,
            decision=decision,
            reason=reason.strip(),
        )
    )
    version.status = "review"
    session.flush()
    return candidate


def review_all_candidates(
    session: Session,
    version_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    decision: str = "accepted",
) -> int:
    candidates = list(
        session.scalars(
            select(PrerequisiteCandidate).where(
                PrerequisiteCandidate.curriculum_version_id == version_id,
                PrerequisiteCandidate.status == "draft",
            )
        )
    )
    for candidate in candidates:
        review_candidate(session, version_id, candidate.id, reviewer_id, decision, "Fixture/source review")
    return len(candidates)


# @spec CURR-VERSION-005
def ensure_version_exercises(session: Session, version: CurriculumVersion) -> int:
    """Give every playable node in a published version a graded run of lessons.

    Procedural only, deliberately: publication is the one path that must stay
    deterministic and offline, and a provider outage or an exhausted course
    budget partway through would abort a graph write. The richer LLM-composed
    score is an explicit later call per exercise.

    Called on both publication paths -- the one that publishes and the one that
    finds the version already published -- because generation is idempotent and
    a re-seed of an existing database must be able to backfill.
    """
    if version.status != "published":
        return 0
    course = session.get(Course, version.course_id)
    instrument = session.scalar(select(Instrument.slug).where(Instrument.id == version.instrument_id))
    if course is None or instrument is None:
        return 0

    # `assessment_capability` already exists on CurriculumNode and already holds
    # {"assessable": bool}, so an optional per-node `performance` block rides
    # along with no migration.
    overrides_by_slug: dict[str, dict[str, object]] = {}
    rows = session.execute(
        select(CurriculumNode, SkillDefinition)
        .join(SkillDefinition, SkillDefinition.id == CurriculumNode.skill_definition_id)
        .where(CurriculumNode.curriculum_version_id == version.id)
    )
    for curriculum_node, definition in rows:
        capability = curriculum_node.assessment_capability or {}
        performance = capability.get("performance") if isinstance(capability, dict) else None
        if isinstance(performance, dict):
            overrides_by_slug[definition.slug] = performance

    created = 0
    nodes = session.scalars(select(SkillNode).where(SkillNode.curriculum_version_id == version.id))
    for node in nodes:
        # A run of graded lessons, not one exercise. A skill is somewhere a
        # learner arrives before they can pass it, and the tree needs to hold
        # that middle ground rather than only its two ends.
        created += len(
            score_service.ensure_lesson_set_for_node(
                session,
                course=course,
                node=node,
                instrument=instrument,
                overrides=overrides_by_slug.get(node.slug),
            )
        )
    return created


# @spec CURR-VERSION-001, CURR-VERSION-005, CURR-VERSION-007
# @spec CURR-VERSION-010
def publish(
    session: Session,
    version_id: uuid.UUID,
) -> CurriculumPublishResult:
    """Publish exactly once, then project the approved version to skill nodes."""
    version = session.get(CurriculumVersion, version_id)
    if version is None:
        raise LookupError("Curriculum version not found.")
    if version.status == "published":
        nodes = list(session.scalars(select(SkillNode).where(SkillNode.curriculum_version_id == version.id)))
        edges = list(
            session.scalars(
                select(PrerequisiteCandidate).where(
                    PrerequisiteCandidate.curriculum_version_id == version.id,
                    PrerequisiteCandidate.status == "accepted",
                )
            )
        )
        course = session.get(Course, version.course_id)
        ensure_version_exercises(session, version)
        return CurriculumPublishResult(version.id, course.graph_version, len(nodes), len(edges))
    if version.status == "retired":
        raise ValueError("Retired curriculum versions cannot be published.")

    candidates = list(
        session.scalars(select(PrerequisiteCandidate).where(PrerequisiteCandidate.curriculum_version_id == version.id))
    )
    pending = [candidate for candidate in candidates if candidate.status in {"draft", "ambiguous"}]
    if pending:
        raise ValueError("Every curriculum candidate needs an explicit review before publication.")
    accepted = [candidate for candidate in candidates if candidate.status == "accepted"]
    evidence_counts = {
        candidate.id: session.scalar(
            select(func.count(CurriculumEvidence.id)).where(CurriculumEvidence.candidate_id == candidate.id)
        )
        for candidate in accepted
    }
    # Same rule as review: justifiable, not necessarily quoted. See the note in
    # `review_candidate` -- an edge that never read a document owes a rationale
    # rather than a quote, and the two are checked together so the review gate
    # and the publication gate cannot disagree about what a justification is.
    unjustified = [
        candidate
        for candidate in accepted
        if not evidence_counts[candidate.id] and not (candidate.rationale or "").strip()
    ]
    if unjustified:
        raise ValueError(
            "Every accepted curriculum edge needs a justification before publication: "
            "an evidence quote, or a recorded rationale where no document was read."
        )

    node_rows = list(
        session.execute(
            select(CurriculumNode, SkillDefinition)
            .join(SkillDefinition, SkillDefinition.id == CurriculumNode.skill_definition_id)
            .where(CurriculumNode.curriculum_version_id == version.id)
            .order_by(CurriculumNode.position)
        )
    )
    if not node_rows:
        raise ValueError("A curriculum version cannot publish without nodes.")
    concepts = [
        ConceptSpec(
            slug=definition.slug,
            title=definition.title,
            summary=definition.summary,
            difficulty=definition.difficulty,
            assessable=definition.assessable,
            source_chunk_ids=tuple(node.source_chunk_ids),
            section=node.section,
        )
        for node, definition in node_rows
    ]
    definition_by_id = {definition.id: definition for _, definition in node_rows}
    edges = [
        CandidateEdge(
            prereq=definition_by_id[candidate.prereq_skill_id].slug,
            target=definition_by_id[candidate.target_skill_id].slug,
            confidence=candidate.confidence,
            support=candidate.support,
            rationale=candidate.rationale or "",
        )
        for candidate in accepted
    ]
    build_acyclic_edges({concept.slug for concept in concepts}, edges, min_confidence=0.0)
    # Refusals the compiler made when this draft was built. A candidate a *human*
    # rejected carries no rejection_reason and is deliberately excluded: it is a
    # review decision, and replaying it through the graph writer would let an
    # acyclic edge a reviewer turned down be silently re-admitted.
    refusals = [
        RejectedEdge(
            prereq=definition_by_id[candidate.prereq_skill_id].slug,
            target=definition_by_id[candidate.target_skill_id].slug,
            reason=candidate.rejection_reason,
            confidence=candidate.confidence,
            cycle_path=tuple(candidate.cycle_path or ()),
            support=candidate.support,
            rationale=candidate.rationale or "",
        )
        for candidate in candidates
        if candidate.status == "rejected"
        and candidate.rejection_reason
        and candidate.prereq_skill_id in definition_by_id
        and candidate.target_skill_id in definition_by_id
    ]
    course = session.get(Course, version.course_id)
    if course is None:
        raise LookupError("Curriculum course not found.")
    written = persist_graph(session, course, concepts, edges, min_confidence=0.0, prior_rejections=refusals)
    projected_nodes = {
        node.slug: node
        for node in session.scalars(select(SkillNode).where(SkillNode.course_id == course.id))
    }
    for _, definition in node_rows:
        projected = projected_nodes.get(definition.slug)
        if projected is not None:
            projected.curriculum_version_id = version.id
            projected.skill_definition_id = definition.id

    previous = list(
        session.scalars(
            select(CurriculumVersion).where(
                CurriculumVersion.course_id == version.course_id,
                CurriculumVersion.slug == version.slug,
                CurriculumVersion.status == "published",
                CurriculumVersion.id != version.id,
            )
        )
    )
    for old_version in previous:
        old_version.status = "retired"
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    session.flush()
    # After the status flips, not before: `ensure_version_exercises` refuses to
    # touch a draft, which is the same gate that stops an unreviewed graph
    # affecting unlocks. Generating exercises for a draft would be exactly the
    # leak publication exists to prevent.
    ensure_version_exercises(session, version)
    return CurriculumPublishResult(
        version.id,
        written.graph_version,
        written.node_count,
        written.edges_accepted,
        written.edges_rendered,
        written.max_depth,
    )


# @spec CURR-VERSION-006
def seed_published_curriculum(
    session: Session,
    course: Course,
    instrument_slug: str,
    instrument_title: str,
    curriculum_slug: str,
    title: str,
    concepts: Sequence[ConceptSpec],
    candidates: Sequence[CandidateEdge],
    evidence_by_edge: Mapping[tuple[str, str], Sequence[EvidenceSpec]],
    reviewer_id: uuid.UUID,
    compiler_version: str = CURRICULUM_COMPILER_VERSION,
) -> CurriculumPublishResult:
    existing = session.scalar(
        select(CurriculumVersion).where(
            CurriculumVersion.course_id == course.id,
            CurriculumVersion.slug == curriculum_slug,
            CurriculumVersion.status == "published",
        )
    )
    if existing is not None:
        return publish(session, existing.id)
    draft = create_draft(
        session,
        course,
        instrument_slug,
        instrument_title,
        curriculum_slug,
        title,
        concepts,
        candidates,
        evidence_by_edge=evidence_by_edge,
        compiler_version=compiler_version,
    )
    review_all_candidates(session, draft.version_id, reviewer_id)
    return publish(session, draft.version_id)


def _concept_specs(payload: CurriculumVersionCreate) -> list[ConceptSpec]:
    return [
        ConceptSpec(
            slug=concept.slug,
            title=concept.title,
            summary=concept.summary,
            difficulty=concept.difficulty,
            assessable=concept.assessable,
            key_terms=tuple(concept.key_terms),
            source_chunk_ids=tuple(concept.source_chunk_ids),
            section=concept.section,
        )
        for concept in payload.concepts
    ]


def _candidate_inputs(payload: CurriculumVersionCreate) -> tuple[list[CandidateEdge], dict[tuple[str, str], list[EvidenceSpec]]]:
    candidates: list[CandidateEdge] = []
    evidence: dict[tuple[str, str], list[EvidenceSpec]] = {}
    for edge in payload.edges:
        pair = (edge.prereq, edge.target)
        candidates.append(
            CandidateEdge(
                prereq=edge.prereq,
                target=edge.target,
                confidence=edge.confidence,
                support=edge.support,
                rationale=edge.rationale,
            )
        )
        evidence[pair] = [
            EvidenceSpec(
                chunk_id=item.chunk_id,
                quote=item.quote,
                extractor_version=item.extractor_version,
                prompt_sha256=item.prompt_sha256,
                source_sha256=item.source_sha256,
            )
            for item in edge.evidence
        ]
    return candidates, evidence


def _project_version(session: Session, version_id: uuid.UUID) -> CurriculumVersionOut:
    row = session.execute(
        select(CurriculumVersion, Instrument).join(Instrument, Instrument.id == CurriculumVersion.instrument_id).where(
            CurriculumVersion.id == version_id
        )
    ).one()
    version, instrument = row
    node_count = session.scalar(
        select(func.count(CurriculumNode.skill_definition_id)).where(CurriculumNode.curriculum_version_id == version_id)
    )
    candidate_count = session.scalar(
        select(func.count(PrerequisiteCandidate.id)).where(
            PrerequisiteCandidate.curriculum_version_id == version_id,
            PrerequisiteCandidate.status == "accepted",
        )
    )
    rejected_count = session.scalar(
        select(func.count(PrerequisiteCandidate.id)).where(
            PrerequisiteCandidate.curriculum_version_id == version_id,
            PrerequisiteCandidate.status == "rejected",
        )
    )
    return CurriculumVersionOut(
        id=version.id,
        course_id=version.course_id,
        instrument=instrument.slug,
        slug=version.slug,
        title=version.title,
        version=version.version,
        status=version.status,
        compiler_version=version.compiler_version,
        node_count=int(node_count or 0),
        candidate_count=int(candidate_count or 0),
        rejected_count=int(rejected_count or 0),
        created_at=version.created_at,
        published_at=version.published_at,
    )


def _project_candidate(session: Session, candidate_id: uuid.UUID) -> CurriculumCandidateOut:
    prereq_definition = aliased(SkillDefinition)
    target_definition = aliased(SkillDefinition)
    row = session.execute(
        select(PrerequisiteCandidate, prereq_definition, target_definition)
        .join(prereq_definition, prereq_definition.id == PrerequisiteCandidate.prereq_skill_id)
        .join(target_definition, target_definition.id == PrerequisiteCandidate.target_skill_id)
        .where(PrerequisiteCandidate.id == candidate_id)
    ).one()
    candidate = row[0]
    evidence_count = session.scalar(
        select(func.count(CurriculumEvidence.id)).where(CurriculumEvidence.candidate_id == candidate.id)
    )
    return CurriculumCandidateOut(
        id=candidate.id,
        version_id=candidate.curriculum_version_id,
        prereq=row[1].slug,
        target=row[2].slug,
        confidence=candidate.confidence,
        support=candidate.support,
        status=candidate.status,
        rationale=candidate.rationale,
        rejection_reason=candidate.rejection_reason,
        cycle_path=list(candidate.cycle_path),
        evidence_count=int(evidence_count or 0),
    )


async def create_version_api(session: AsyncSession, course: Course, payload: CurriculumVersionCreate) -> CurriculumVersionOut:
    concepts = _concept_specs(payload)
    candidates, evidence = _candidate_inputs(payload)
    result = await session.run_sync(
        lambda sync: create_draft(
            sync,
            course,
            payload.instrument,
            payload.instrument_title,
            payload.slug,
            payload.title,
            concepts,
            candidates,
            evidence_by_edge=evidence,
            source_bundle_sha256=payload.source_bundle_sha256,
            compiler_version=payload.compiler_version,
        )
    )
    await session.commit()
    return await session.run_sync(lambda sync: _project_version(sync, result.version_id))


def _project_candidates(session: Session, version_id: uuid.UUID) -> list[CurriculumCandidateOut]:
    candidate_ids = list(
        session.scalars(
            select(PrerequisiteCandidate.id)
            .where(PrerequisiteCandidate.curriculum_version_id == version_id)
            .order_by(PrerequisiteCandidate.created_at, PrerequisiteCandidate.id)
        )
    )
    return [_project_candidate(session, candidate_id) for candidate_id in candidate_ids]


async def list_candidates_api(
    session: AsyncSession,
    course: Course,
    version_id: uuid.UUID,
) -> list[CurriculumCandidateOut]:
    def operation(sync: Session) -> list[CurriculumCandidateOut]:
        version = sync.get(CurriculumVersion, version_id)
        if version is None or version.course_id != course.id:
            raise LookupError("Curriculum version not found.")
        return _project_candidates(sync, version_id)

    return await session.run_sync(operation)


async def review_candidate_api(
    session: AsyncSession,
    course: Course,
    version_id: uuid.UUID,
    candidate_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    decision: str,
    reason: str,
) -> CurriculumCandidateOut:
    def operation(sync: Session) -> CurriculumCandidateOut:
        version = sync.get(CurriculumVersion, version_id)
        if version is None or version.course_id != course.id:
            raise LookupError("Curriculum version not found.")
        review_candidate(sync, version_id, candidate_id, reviewer_id, decision, reason)
        return _project_candidate(sync, candidate_id)

    result = await session.run_sync(operation)
    await session.commit()
    return result



async def publish_api(
    session: AsyncSession,
    course: Course,
    version_id: uuid.UUID,
) -> CurriculumPublishOut:
    def operation(sync: Session) -> CurriculumPublishOut:
        version = sync.get(CurriculumVersion, version_id)
        if version is None or version.course_id != course.id:
            raise LookupError("Curriculum version not found.")
        result = publish(sync, version_id)
        return CurriculumPublishOut(
            version_id=result.version_id,
            course_id=course.id,
            graph_version=result.graph_version,
            node_count=result.node_count,
            edge_count=result.edge_count,
        )

    result = await session.run_sync(operation)
    await session.commit()
    return result
