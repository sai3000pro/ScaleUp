r"""Idempotent development seed.

Creates a fixed-UUID dev user, two courses the project offers ready-made (piano
and guitar), and four internal courses (trumpet, drums, banjo, and a
source-generated violin), so the frontend, the SRS, the quest board, and state
derivation are all developable and testable with **zero LLM calls and zero ingest
latency**. Per line of code this is the highest-leverage file in the project.

Which shelf each course lands on is declared in `app.core.shelves`, not inferred
from anything here.

The trumpet course deliberately carries two things a real extractor produces and
the pipeline must handle:

* a **back-edge** (simple-trumpet-melody -> long-tones) that would close a cycle,
  so `skill_edge_rejections` is populated and the rejection UI has real data;
* a **transitively implied edge** (trumpet-orientation -> long-tones) that
  survives storage but is dropped from the rendered set.

    cd backend
    .\.venv\Scripts\python.exe -m app.seed
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace

from sqlalchemy import delete, select

from app.core.dev_user import DEV_DISPLAY_NAME, DEV_EMAIL, DEV_PASSWORD, DEV_USER_ID
from app.core.security import hash_password
from app.core.shelves import (
    BANJO_COURSE_ID,
    DRUMS_COURSE_ID,
    GUITAR_COURSE_ID,
    PIANO_COURSE_ID,
    RETIRED_LINEAR_ALGEBRA_COURSE_ID,
    TRUMPET_COURSE_ID,
    VIOLIN_COURSE_ID,
)
from app.curricula.loader import CurriculumDefinition, load_curriculum
from app.curricula.source import compile_source_sections, load_source_sections
from app.db.session import sync_session
from app.domain.dag import CandidateEdge
from app.evaluation.musicxml import parse_musicxml
from app.evaluation.reference_scores import (
    DRUMS_ROCK_GROOVE_XML,
    GUITAR_GCD_STRUM_XML,
    GUITAR_LOW_E_FRETTING_XML,
    PIANO_STEPWISE_SCORE_XML,
    TRUMPET_C_ARPEGGIO_XML,
    VIOLIN_OPEN_STRINGS_XML,
)
from app.models import Chunk, Course, Document, Exercise, ScoreAsset, SkillEdgeRejection, SkillNode, User
from app.services.curriculum_graph_service import EvidenceSpec, seed_published_curriculum
from app.services.graph_service import ConceptSpec

# DEV_USER_ID, DEV_EMAIL, DEV_PASSWORD and DEV_DISPLAY_NAME are imported above
# from app.core.dev_user, which owns them so that auth_service can provision the
# dev user without importing this module -- this one imports graph_service, and
# that would close an import cycle. They stay importable from here, which is
# where the tests and scripts already reach for them.
#
# The seeded course ids arrive the same way, from app.core.shelves, which also
# declares which of them a learner is offered and which exist only so the system
# is developable offline.
PIANO_EXERCISE_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
PIANO_SCORE_ASSET_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
GUITAR_EXERCISE_ID = uuid.UUID("00000000-0000-4000-8000-000000000012")
GUITAR_SCORE_ASSET_ID = uuid.UUID("00000000-0000-4000-8000-000000000013")

PIANO_DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000005")
GUITAR_DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000007")
VIOLIN_DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000009")
TRUMPET_DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000015")
DRUMS_DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000017")
BANJO_DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000019")
VIOLIN_EXERCISE_ID = uuid.UUID("00000000-0000-4000-8000-000000000018")
VIOLIN_SCORE_ASSET_ID = uuid.UUID("00000000-0000-4000-8000-000000000019")
TRUMPET_EXERCISE_ID = uuid.UUID("00000000-0000-4000-8000-000000000020")
TRUMPET_SCORE_ASSET_ID = uuid.UUID("00000000-0000-4000-8000-000000000021")
DRUMS_EXERCISE_ID = uuid.UUID("00000000-0000-4000-8000-000000000022")
DRUMS_SCORE_ASSET_ID = uuid.UUID("00000000-0000-4000-8000-000000000023")
GUITAR_CHORD_EXERCISE_ID = uuid.UUID("00000000-0000-4000-8000-000000000024")
GUITAR_CHORD_SCORE_ASSET_ID = uuid.UUID("00000000-0000-4000-8000-000000000025")


#: Two things a real extractor produces and the pipeline must handle, planted on
#: the trumpet course so both have a worked example in a seeded database.
#:
#: They live on an internal course rather than one the project offers: neither is
#: visible in a rendered tree -- one is rejected, the other reduced away -- but a
#: rejection log full of deliberate mistakes is not what an offered course should
#: carry. Both read like claims a model would actually make, which is the point.
PLANTED_TRUMPET_EDGES: list[CandidateEdge] = [
    # Transitively implied by trumpet-orientation -> embouchure-basics -> long-tones.
    # Stored, and dropped from the rendered set by transitive reduction.
    CandidateEdge(
        "trumpet-orientation",
        "long-tones",
        0.70,
        rationale="You cannot sustain a tone on an instrument you are not holding correctly.",
    ),
    # Would close a cycle: long-tones already reaches simple-trumpet-melody through
    # major-arpeggios. Rejected, with the offending path recorded -- and the
    # rationale kept, because it is what a reviewer judges the rejection against.
    CandidateEdge(
        "simple-trumpet-melody",
        "long-tones",
        0.38,
        rationale="The melody exercise is where long tones are actually put to use.",
    ),
]


def _seed_chunks(
    session,
    course_id: uuid.UUID,
    document_id: uuid.UUID,
    concepts: list[ConceptSpec],
    filename: str,
) -> dict[str, uuid.UUID]:
    """Give every seeded concept a passage to be questioned about.

    Without source material the question generator is handed
    "(no source material available)" and produces something unanswerable, which
    makes the seeded course useless for developing the drill UI -- the exact
    thing this file exists to enable.
    """
    document = session.get(Document, document_id)
    if document is None:
        document = Document(
            id=document_id,
            course_id=course_id,
            source_type="text",
            filename=filename,
            content_sha256="0" * 64,
            storage_path="(seeded; no file on disk)",
            byte_size=0,
            page_count=1,
        )
        session.add(document)
        session.flush()

    session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    session.flush()

    chunk_ids: dict[str, uuid.UUID] = {}
    for ordinal, concept in enumerate(concepts):
        chunk = Chunk(
            id=uuid.uuid5(document_id, str(ordinal)),
            document_id=document_id,
            course_id=course_id,
            ordinal=ordinal,
            page_start=1,
            page_end=1,
            section_path=concept.title,
            text=(
                f"{concept.title}. {concept.summary} "
                f"This passage explains {concept.title.lower()} and why it matters once you are "
                f"playing with a steady pulse, in tune, and in time with other musicians."
            ),
            token_count=40,
            content_sha256=f"{ordinal:064d}",
        )
        session.add(chunk)
        session.flush()
        chunk_ids[concept.slug] = chunk.id

    return chunk_ids


def _seed_piano_exercise(session, course: Course) -> None:
    node = session.scalar(
        select(SkillNode).where(SkillNode.course_id == course.id, SkillNode.slug == "stepwise-melody")
    )
    if node is None:
        raise ValueError("Piano curriculum is missing the stepwise-melody node.")
    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    content_hash = hashlib.sha256(PIANO_STEPWISE_SCORE_XML.encode("utf-8")).hexdigest()
    asset = session.get(ScoreAsset, PIANO_SCORE_ASSET_ID)
    if asset is None:
        asset = ScoreAsset(
            id=PIANO_SCORE_ASSET_ID,
            course_id=course.id,
            title=score.title,
            format="musicxml",
            content=PIANO_STEPWISE_SCORE_XML,
            content_sha256=content_hash,
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
            asset_metadata={"instrument": "piano", "monophonic": True},
        )
        session.add(asset)
    else:
        asset.content = PIANO_STEPWISE_SCORE_XML
        asset.content_sha256 = content_hash
        asset.tempo_bpm = score.tempo_bpm
        asset.duration_beats = score.duration_beats
    exercise = session.get(Exercise, PIANO_EXERCISE_ID)
    if exercise is None:
        exercise = Exercise(
            id=PIANO_EXERCISE_ID,
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug="stepwise-c-major",
            title="Stepwise C Major",
            instructions="Play the four quarter notes evenly at the marked tempo.",
            evaluator_version="piano-dtw-v1",
            difficulty=node.difficulty,
        )
        session.add(exercise)
    else:
        exercise.node_id = node.id
        exercise.score_asset_id = asset.id
        exercise.difficulty = node.difficulty
        exercise.active = True
    session.flush()


def _seed_guitar_exercise(session, course: Course) -> None:
    node = session.scalar(
        select(SkillNode).where(SkillNode.course_id == course.id, SkillNode.slug == "single-note-fretting")
    )
    if node is None:
        raise ValueError("Guitar curriculum is missing the single-note-fretting node.")
    score = parse_musicxml(GUITAR_LOW_E_FRETTING_XML)
    content_hash = hashlib.sha256(GUITAR_LOW_E_FRETTING_XML.encode("utf-8")).hexdigest()
    asset = session.get(ScoreAsset, GUITAR_SCORE_ASSET_ID)
    if asset is None:
        asset = ScoreAsset(
            id=GUITAR_SCORE_ASSET_ID,
            course_id=course.id,
            title=score.title,
            format="musicxml",
            content=GUITAR_LOW_E_FRETTING_XML,
            content_sha256=content_hash,
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
            asset_metadata={"instrument": "guitar", "monophonic": True},
        )
        session.add(asset)
    else:
        asset.content = GUITAR_LOW_E_FRETTING_XML
        asset.content_sha256 = content_hash
        asset.tempo_bpm = score.tempo_bpm
        asset.duration_beats = score.duration_beats
    exercise = session.get(Exercise, GUITAR_EXERCISE_ID)
    if exercise is None:
        exercise = Exercise(
            id=GUITAR_EXERCISE_ID,
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug="low-e-fretting",
            title="Low E Fretting Drill",
            instructions="Fret the four notes on the low E string with a clean attack.",
            evaluator_version="guitar-dtw-v1",
            difficulty=node.difficulty,
        )
        session.add(exercise)
    else:
        exercise.node_id = node.id
        exercise.score_asset_id = asset.id
        exercise.difficulty = node.difficulty
        exercise.active = True
    session.flush()


def _seed_guitar_chord_exercise(session, course: Course) -> None:
    node = session.scalar(
        select(SkillNode).where(SkillNode.course_id == course.id, SkillNode.slug == "open-chords")
    )
    if node is None:
        raise ValueError("Guitar curriculum is missing the open-chords node.")
    score = parse_musicxml(GUITAR_GCD_STRUM_XML)
    content_hash = hashlib.sha256(GUITAR_GCD_STRUM_XML.encode("utf-8")).hexdigest()
    asset = session.get(ScoreAsset, GUITAR_CHORD_SCORE_ASSET_ID)
    if asset is None:
        asset = ScoreAsset(
            id=GUITAR_CHORD_SCORE_ASSET_ID,
            course_id=course.id,
            title=score.title,
            format="musicxml",
            content=GUITAR_GCD_STRUM_XML,
            content_sha256=content_hash,
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
            asset_metadata={"instrument": "guitar", "style": "chords"},
        )
        session.add(asset)
    else:
        asset.content = GUITAR_GCD_STRUM_XML
        asset.content_sha256 = content_hash
        asset.tempo_bpm = score.tempo_bpm
        asset.duration_beats = score.duration_beats
    exercise = session.get(Exercise, GUITAR_CHORD_EXERCISE_ID)
    if exercise is None:
        exercise = Exercise(
            id=GUITAR_CHORD_EXERCISE_ID,
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug="g-c-d-strum",
            title="G C D Strum",
            instructions="Strum the G, C, and D open chords once per beat, keeping the pulse even.",
            evaluator_version="guitar-chords-v1",
            difficulty=node.difficulty,
        )
        session.add(exercise)
    else:
        exercise.node_id = node.id
        exercise.score_asset_id = asset.id
        exercise.difficulty = node.difficulty
        exercise.active = True
    session.flush()


def _seed_violin_exercise(session, course: Course) -> None:
    node = session.scalar(
        select(SkillNode).where(SkillNode.course_id == course.id, SkillNode.slug == "open-string-bow")
    )
    if node is None:
        raise ValueError("Violin curriculum is missing the open-string-bow node.")
    score = parse_musicxml(VIOLIN_OPEN_STRINGS_XML)
    content_hash = hashlib.sha256(VIOLIN_OPEN_STRINGS_XML.encode("utf-8")).hexdigest()
    asset = session.get(ScoreAsset, VIOLIN_SCORE_ASSET_ID)
    if asset is None:
        asset = ScoreAsset(
            id=VIOLIN_SCORE_ASSET_ID,
            course_id=course.id,
            title=score.title,
            format="musicxml",
            content=VIOLIN_OPEN_STRINGS_XML,
            content_sha256=content_hash,
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
            asset_metadata={"instrument": "violin", "monophonic": True},
        )
        session.add(asset)
    else:
        asset.content = VIOLIN_OPEN_STRINGS_XML
        asset.content_sha256 = content_hash
        asset.tempo_bpm = score.tempo_bpm
        asset.duration_beats = score.duration_beats
    exercise = session.get(Exercise, VIOLIN_EXERCISE_ID)
    if exercise is None:
        exercise = Exercise(
            id=VIOLIN_EXERCISE_ID,
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug="open-string-scale",
            title="Open String Scale",
            instructions="Bow each open string with a straight, steady stroke at the marked tempo.",
            evaluator_version="violin-dtw-v1",
            difficulty=node.difficulty,
        )
        session.add(exercise)
    else:
        exercise.node_id = node.id
        exercise.score_asset_id = asset.id
        exercise.difficulty = node.difficulty
        exercise.active = True
    session.flush()


def _seed_trumpet_exercise(session, course: Course) -> None:
    node = session.scalar(
        select(SkillNode).where(SkillNode.course_id == course.id, SkillNode.slug == "major-arpeggios")
    )
    if node is None:
        raise ValueError("Trumpet curriculum is missing the major-arpeggios node.")
    score = parse_musicxml(TRUMPET_C_ARPEGGIO_XML)
    content_hash = hashlib.sha256(TRUMPET_C_ARPEGGIO_XML.encode("utf-8")).hexdigest()
    asset = session.get(ScoreAsset, TRUMPET_SCORE_ASSET_ID)
    if asset is None:
        asset = ScoreAsset(
            id=TRUMPET_SCORE_ASSET_ID,
            course_id=course.id,
            title=score.title,
            format="musicxml",
            content=TRUMPET_C_ARPEGGIO_XML,
            content_sha256=content_hash,
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
            asset_metadata={"instrument": "trumpet", "monophonic": True},
        )
        session.add(asset)
    else:
        asset.content = TRUMPET_C_ARPEGGIO_XML
        asset.content_sha256 = content_hash
        asset.tempo_bpm = score.tempo_bpm
        asset.duration_beats = score.duration_beats
    exercise = session.get(Exercise, TRUMPET_EXERCISE_ID)
    if exercise is None:
        exercise = Exercise(
            id=TRUMPET_EXERCISE_ID,
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug="c-major-arpeggio",
            title="C Major Arpeggio",
            instructions="Play the four notes with clean attacks and steady air.",
            evaluator_version="trumpet-dtw-v1",
            difficulty=node.difficulty,
        )
        session.add(exercise)
    else:
        exercise.node_id = node.id
        exercise.score_asset_id = asset.id
        exercise.difficulty = node.difficulty
        exercise.active = True
    session.flush()


def _seed_drums_exercise(session, course: Course) -> None:
    node = session.scalar(
        select(SkillNode).where(SkillNode.course_id == course.id, SkillNode.slug == "eighth-note-groove")
    )
    if node is None:
        raise ValueError("Drums curriculum is missing the eighth-note-groove node.")
    score = parse_musicxml(DRUMS_ROCK_GROOVE_XML)
    content_hash = hashlib.sha256(DRUMS_ROCK_GROOVE_XML.encode("utf-8")).hexdigest()
    asset = session.get(ScoreAsset, DRUMS_SCORE_ASSET_ID)
    if asset is None:
        asset = ScoreAsset(
            id=DRUMS_SCORE_ASSET_ID,
            course_id=course.id,
            title=score.title,
            format="musicxml",
            content=DRUMS_ROCK_GROOVE_XML,
            content_sha256=content_hash,
            tempo_bpm=score.tempo_bpm,
            duration_beats=score.duration_beats,
            asset_metadata={"instrument": "drums", "monophonic": False, "rhythm_only": True},
        )
        session.add(asset)
    else:
        asset.content = DRUMS_ROCK_GROOVE_XML
        asset.content_sha256 = content_hash
        asset.tempo_bpm = score.tempo_bpm
        asset.duration_beats = score.duration_beats
    exercise = session.get(Exercise, DRUMS_EXERCISE_ID)
    if exercise is None:
        exercise = Exercise(
            id=DRUMS_EXERCISE_ID,
            course_id=course.id,
            node_id=node.id,
            score_asset_id=asset.id,
            slug="rock-groove",
            title="Rock Groove",
            instructions="Keep the hi-hat eighths steady with kick on beats 1 and 3, snare on 2 and 4.",
            evaluator_version="drums-rhythm-v1",
            difficulty=node.difficulty,
        )
        session.add(exercise)
    else:
        exercise.node_id = node.id
        exercise.score_asset_id = asset.id
        exercise.difficulty = node.difficulty
        exercise.active = True
    session.flush()


def _seed_source_chunks(
    session,
    course_id: uuid.UUID,
    document_id: uuid.UUID,
    sections,
    filename: str,
) -> dict[str, uuid.UUID]:
    document = session.get(Document, document_id)
    if document is None:
        document = Document(
            id=document_id,
            course_id=course_id,
            source_type="text",
            filename=filename,
            content_sha256="0" * 64,
            storage_path="(seeded from source sections; no file on disk)",
            byte_size=0,
            page_count=1,
        )
        session.add(document)
        session.flush()
    session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    session.flush()
    chunk_ids: dict[str, uuid.UUID] = {}
    for ordinal, section in enumerate(sections):
        chunk_id = uuid.uuid5(document_id, str(ordinal))
        session.add(
            Chunk(
                id=chunk_id,
                document_id=document_id,
                course_id=course_id,
                ordinal=ordinal,
                page_start=1,
                page_end=1,
                section_path=section.title,
                text=section.text,
                token_count=max(1, len(section.text.split())),
                content_sha256=hashlib.sha256(section.text.encode("utf-8")).hexdigest(),
            )
        )
        chunk_ids[section.slug] = chunk_id
    session.flush()
    return chunk_ids


def _seed_source_curriculum_course(
    session,
    course: Course,
    document_id: uuid.UUID,
    filename: str,
    instrument: str,
    instrument_title: str,
    curriculum_slug: str,
    title: str,
    sections,
):
    bundle = compile_source_sections(sections)
    chunk_ids = _seed_source_chunks(session, course.id, document_id, sections, filename)
    concepts = [
        replace(concept, source_chunk_ids=(chunk_ids[concept.slug],))
        for concept in bundle.concepts
    ]
    evidence = {
        pair: (EvidenceSpec(chunk_id=chunk_ids[pair[1]], quote=quote),)
        for pair, quote in bundle.evidence_quotes.items()
    }
    published = seed_published_curriculum(
        session,
        course,
        instrument,
        instrument_title,
        curriculum_slug,
        title,
        concepts,
        list(bundle.edges),
        evidence,
        DEV_USER_ID,
    )
    from app.services.graph_service import GraphWriteResult

    return GraphWriteResult(
        node_count=published.node_count,
        edges_accepted=published.edge_count,
        edges_rejected=0,
        edges_rendered=published.rendered_edge_count,
        max_depth=published.max_depth,
        graph_version=published.graph_version,
    )


def _concept_specs(curriculum: CurriculumDefinition) -> list[ConceptSpec]:
    return [
        ConceptSpec(
            slug=concept.slug,
            title=concept.title,
            summary=concept.summary,
            difficulty=concept.difficulty,
            key_terms=concept.key_terms,
        )
        for concept in curriculum.concepts
    ]


def _seed_curriculum_course(
    session,
    course: Course,
    document_id: uuid.UUID,
    filename: str,
    curriculum: CurriculumDefinition,
    extra_edges: list[CandidateEdge] | None = None,
):
    """Publish a curriculum, optionally with edges the curriculum itself does not claim.

    `extra_edges` exists for `PLANTED_TRUMPET_EDGES` and nothing else: the
    published curricula are clean, and the two pathologies a real extractor
    produces have to come from somewhere the compiler can still reject them.
    """
    specs = _concept_specs(curriculum)
    chunk_ids = _seed_chunks(session, course.id, document_id, specs, filename)
    specs_with_sources = [
        replace(concept, source_chunk_ids=(chunk_ids[concept.slug],)) for concept in specs
    ]
    evidence = {
        (edge.prereq, edge.target): (
            EvidenceSpec(
                chunk_id=chunk_ids[edge.target],
                quote=next(concept.summary for concept in specs if concept.slug == edge.target),
            ),
        )
        for edge in curriculum.edges
    }
    published = seed_published_curriculum(
        session,
        course,
        curriculum.instrument,
        curriculum.instrument.title(),
        curriculum.slug,
        curriculum.title,
        specs_with_sources,
        [*curriculum.edges, *(extra_edges or [])],
        evidence,
        DEV_USER_ID,
    )
    from app.services.graph_service import GraphWriteResult

    return GraphWriteResult(
        node_count=published.node_count,
        edges_accepted=published.edge_count,
        edges_rejected=0,
        edges_rendered=published.rendered_edge_count,
        max_depth=published.max_depth,
        graph_version=published.graph_version,
    )


def _seeded_course(session, course_id: uuid.UUID, title: str, description: str) -> Course:
    """Create or refresh a course the seed owns.

    Unlike a learner's course, the title and blurb on a seeded one are the
    project's own presentation, so re-seeding brings them current rather than
    leaving whatever an earlier run wrote. Progress, nodes and edges are
    untouched: this reconciles how a course is described, not the tree.
    """
    course = session.get(Course, course_id)
    if course is None:
        course = Course(id=course_id, owner_id=DEV_USER_ID, title=title, description=description)
        session.add(course)
    else:
        course.title = title
        course.description = description
    session.flush()
    return course


# @spec OPS-CI-005
def seed() -> None:
    with sync_session() as session:
        user = session.get(User, DEV_USER_ID)
        if user is None:
            user = User(
                id=DEV_USER_ID,
                email=DEV_EMAIL,
                password_hash=hash_password(DEV_PASSWORD),
                display_name=DEV_DISPLAY_NAME,
            )
            session.add(user)
            print(f"created dev user   {DEV_EMAIL} / {DEV_PASSWORD}")
        else:
            print(f"dev user exists    {DEV_EMAIL}")

        # The linear-algebra tree predates the instrument product. It is retired
        # rather than hidden: leaving the row in place keeps a course nobody can
        # practise standing in every development database forever. Removing it here
        # means one `python -m app.seed` clears it, with no migration.
        retired = session.get(Course, RETIRED_LINEAR_ALGEBRA_COURSE_ID)
        if retired is not None:
            session.delete(retired)
            session.flush()
            print("retired            Linear Algebra")
        else:
            pass

        piano_course = _seeded_course(
            session,
            PIANO_COURSE_ID,
            "Piano",
            "A ready-made piano skill tree — start here if you have not picked a goal yet.",
        )

        piano_result = _seed_curriculum_course(
            session,
            piano_course,
            PIANO_DOCUMENT_ID,
            "piano-passages.txt",
            load_curriculum("piano"),
        )

        _seed_piano_exercise(session, piano_course)
        print(f"piano course       {piano_course.id}")
        print(f"piano nodes        {piano_result.node_count}")
        print(f"piano edges        {piano_result.edges_rendered} rendered / {piano_result.edges_accepted} accepted")
        print("piano exercise     stepwise-c-major")

        guitar_course = _seeded_course(
            session,
            GUITAR_COURSE_ID,
            "Guitar",
            "A ready-made guitar skill tree — start here if you have not picked a goal yet.",
        )

        guitar_result = _seed_curriculum_course(
            session,
            guitar_course,
            GUITAR_DOCUMENT_ID,
            "guitar-passages.txt",
            load_curriculum("guitar"),
        )

        _seed_guitar_exercise(session, guitar_course)
        _seed_guitar_chord_exercise(session, guitar_course)
        print(f"guitar course      {guitar_course.id}")
        print(f"guitar nodes       {guitar_result.node_count}")
        print(f"guitar edges       {guitar_result.edges_rendered} rendered / {guitar_result.edges_accepted} accepted")
        print("guitar exercises   low-e-fretting, g-c-d-strum")

        violin_course = _seeded_course(
            session,
            VIOLIN_COURSE_ID,
            "Violin",
            "Compiled from source sections by the reviewed curriculum compiler, with no violin-specific code.",
        )
        violin_instrument, violin_slug, violin_title, violin_sections = load_source_sections("violin-source")
        violin_result = _seed_source_curriculum_course(
            session,
            violin_course,
            VIOLIN_DOCUMENT_ID,
            "violin-sections.txt",
            violin_instrument,
            "Violin",
            violin_slug,
            violin_title,
            violin_sections,
        )
        _seed_violin_exercise(session, violin_course)
        print(f"violin course      {violin_course.id}")
        print(f"violin nodes       {violin_result.node_count} (source-generated)")
        print(f"violin edges       {violin_result.edges_rendered} rendered / {violin_result.edges_accepted} accepted")
        print("violin exercise    open-string-scale")

        trumpet_course = _seeded_course(
            session,
            TRUMPET_COURSE_ID,
            "Trumpet",
            "Loaded from the published trumpet curriculum. No LLM calls were involved.",
        )

        trumpet_result = _seed_curriculum_course(
            session,
            trumpet_course,
            TRUMPET_DOCUMENT_ID,
            "trumpet-passages.txt",
            load_curriculum("trumpet"),
            PLANTED_TRUMPET_EDGES,
        )
        _seed_trumpet_exercise(session, trumpet_course)
        print(f"trumpet course     {trumpet_course.id}")
        print(f"trumpet nodes      {trumpet_result.node_count}")
        print(f"trumpet edges      {trumpet_result.edges_rendered} rendered / {trumpet_result.edges_accepted} accepted")
        print("trumpet exercise   c-major-arpeggio")

        rejections = session.scalars(
            select(SkillEdgeRejection).where(SkillEdgeRejection.course_id == trumpet_course.id)
        )
        for rejection in rejections:
            path = " -> ".join(rejection.cycle_path) if rejection.cycle_path else "-"
            print(f"  rejected {rejection.prereq_slug} -> {rejection.target_slug} [{rejection.reason}] {path}")

        drums_course = _seeded_course(
            session,
            DRUMS_COURSE_ID,
            "Drums",
            "Loaded from the published drums curriculum. No LLM calls were involved.",
        )

        drums_result = _seed_curriculum_course(
            session,
            drums_course,
            DRUMS_DOCUMENT_ID,
            "drums-passages.txt",
            load_curriculum("drums"),
        )
        _seed_drums_exercise(session, drums_course)
        print(f"drums course       {drums_course.id}")
        print(f"drums nodes        {drums_result.node_count}")
        print(f"drums edges        {drums_result.edges_rendered} rendered / {drums_result.edges_accepted} accepted")
        print("drums exercise     rock-groove")

        # Banjo carries no instrument-specific code at all: its skills come from
        # the shared catalogue, and it scores through the guitar evaluator
        # because a fretted strummed string instrument is measured the same way.
        banjo_course = _seeded_course(
            session,
            BANJO_COURSE_ID,
            "Banjo",
            "Assembled mostly from the shared skill catalogue. No banjo-specific code exists.",
        )

        banjo_definition = load_curriculum("banjo")
        banjo_result = _seed_curriculum_course(
            session,
            banjo_course,
            BANJO_DOCUMENT_ID,
            "banjo-passages.txt",
            banjo_definition,
        )
        from_catalogue = sum(1 for concept in banjo_definition.concepts if concept.catalogue_id)
        print(f"banjo course       {banjo_course.id}")
        print(f"banjo nodes        {banjo_result.node_count} ({from_catalogue} from the shared catalogue)")
        print(f"banjo edges        {banjo_result.edges_rendered} rendered / {banjo_result.edges_accepted} accepted")


if __name__ == "__main__":
    seed()
