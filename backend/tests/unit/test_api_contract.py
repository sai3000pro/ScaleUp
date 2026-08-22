"""Executable checks for the hand-maintained backend/frontend API seam.

The backend owns the Pydantic response models, while the frontend mirrors their
wire fields in ``frontend/lib/types.ts``. These tests deliberately stay offline:
Pydantic validation and FastAPI route inspection catch contract drift without
requiring Postgres, Redis, Chroma, Neo4j, or an LLM.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args, get_origin

import pytest
from pydantic import BaseModel, TypeAdapter

from app.main import app
from app.schemas.admin import ProjectionStatus, ReindexAccepted, RejectionsPage
from app.schemas.auth import PasswordResetRequested, TokenResponse, UserOut
from app.schemas.campaign import CampaignBriefingOut, CampaignOutcomeEvaluationOut
from app.schemas.character import CharacterSheet
from app.schemas.cost import CourseCost
from app.schemas.course import CourseDetail, CourseList, CourseOut, DocumentSummary, IngestAccepted
from app.schemas.curriculum import (
    CurriculumCandidateOut,
    CurriculumIngestAccepted,
    CurriculumProposalOut,
    CurriculumPublishOut,
    CurriculumVersionOut,
)
from app.schemas.drill import DrillOut, GradeResult
from app.schemas.explore import AskAnswer, CoursePath, SearchResults
from app.schemas.graph import GraphSnapshot
from app.schemas.job import IngestJobOut
from app.schemas.performance import (
    ExerciseOut,
    PerformanceAttemptOut,
    PracticeSessionOut,
    RecordingOut,
    VoiceArtifactOut,
)
from app.schemas.progress import ProgressAnalytics
from app.schemas.quest import QuestBoard
from app.schemas.share import ShareCreated, SharePreview, ShareStatus
from app.schemas.social import CourseLeaderboard

ROOT = Path(__file__).resolve().parents[3]
FRONTEND_TYPES = ROOT / "frontend" / "lib" / "types.ts"


OPENAPI = app.openapi()

_ID = "00000000-0000-0000-0000-000000000001"
_NODE_ID = "00000000-0000-0000-0000-000000000002"
_ATTEMPT_ID = "00000000-0000-0000-0000-000000000003"
_CHUNK_ID = "00000000-0000-0000-0000-000000000004"
_DT = "2026-08-13T12:00:00Z"

_USER = {
    "id": _ID,
    "email": "dev@example.com",
    "display_name": "Dev",
    "total_exp": 120,
    "level": 2,
    "exp_into_level": 20,
    "exp_for_next_level": 100,
    "streak_days": 3,
    "created_at": _DT,
}
_DOCUMENT = {
    "id": _ID,
    "filename": "linear-algebra.pdf",
    "source_type": "pdf",
    "source_uri": None,
    "page_count": 12,
    "chunk_count": 24,
    "created_at": _DT,
}
_COURSE = {
    "id": _ID,
    "title": "Linear Algebra",
    "description": "A small course",
    "status": "ready",
    "shelf": "learner",
    "graph_version": 2,
    "node_count": 4,
    "edge_count": 3,
    "mastered_count": 1,
    "created_at": _DT,
}
_PROGRESS = {
    "state": "available",
    "exp": 40,
    "level": 1,
    "mastery": 0.4,
    "proficiency": 0.35,
    "due_at": _DT,
    "overdue_days": 0.0,
}
_SOURCE = {"document_id": _ID, "section_path": "Vectors / Definition", "page_start": 3}
_EVIDENCE = {
    "chunk_id": _CHUNK_ID,
    "document_id": _ID,
    "section_path": "Vectors / Definition",
    "page_start": 3,
    "excerpt": "A vector has magnitude and direction.",
}
_NODE = {
    "id": _NODE_ID,
    "slug": "vectors",
    "title": "Vectors",
    "summary": "Representations of magnitude and direction.",
    "difficulty": 2,
    "depth": 0,
    "assessable": True,
    "progress": _PROGRESS,
    "blocked_by": [],
    "sources": [_EVIDENCE],
}


# (method, path) -> response model and status. This is the route inventory that
# the frontend actively consumes; accidental route changes fail before a live
# integration test has to discover them.
_ROUTE_CONTRACT = {
    ("POST", "/api/auth/register"): (TokenResponse, 201),
    ("POST", "/api/auth/login"): (TokenResponse, 200),
    ("POST", "/api/auth/refresh"): (TokenResponse, 200),
    ("POST", "/api/auth/password-reset/request"): (PasswordResetRequested, 202),
    ("POST", "/api/auth/password-reset/consume"): (TokenResponse, 200),
    ("POST", "/api/auth/google/exchange"): (TokenResponse, 200),
    ("GET", "/api/auth/me"): (UserOut, 200),
    ("GET", "/api/character"): (CharacterSheet, 200),
    ("POST", "/api/character"): (CharacterSheet, 201),
    ("PATCH", "/api/character"): (CharacterSheet, 200),
    ("POST", "/api/character/perks/{perk_id}"): (CharacterSheet, 200),
    ("POST", "/api/courses"): (CourseOut, 201),
    ("GET", "/api/courses"): (CourseList, 200),
    ("GET", "/api/courses/{course_id}"): (CourseDetail, 200),
    ("GET", "/api/courses/{course_id}/graph"): (GraphSnapshot, 200),
    ("GET", "/api/courses/{course_id}/leaderboard"): (CourseLeaderboard, 200),
    ("POST", "/api/courses/{course_id}/share"): (ShareCreated, 201),
    ("GET", "/api/courses/{course_id}/share"): (ShareStatus, 200),
    ("GET", "/api/shares/{token}"): (SharePreview, 200),
    ("POST", "/api/shares/{token}/copy"): (CourseOut, 201),
    ("GET", "/api/courses/{course_id}/campaign/briefing"): (CampaignBriefingOut, 200),
    ("POST", "/api/courses/{course_id}/campaign/evaluate"): (CampaignOutcomeEvaluationOut, 200),
    ("POST", "/api/courses/{course_id}/curriculum/proposals"): (CurriculumProposalOut, 201),
    ("GET", "/api/courses/{course_id}/curriculum/proposals/latest"): (CurriculumProposalOut, 200),
    ("GET", "/api/courses/{course_id}/curriculum/proposals/{proposal_id}"): (CurriculumProposalOut, 200),
    (
        "POST",
        "/api/courses/{course_id}/curriculum/proposals/{proposal_id}/sources/{source_id}/policy-check",
    ): (CurriculumProposalOut, 200),
    ("POST", "/api/courses/{course_id}/curriculum/proposals/{proposal_id}/approve"): (CurriculumProposalOut, 200),
    ("POST", "/api/courses/{course_id}/curriculum/proposals/{proposal_id}/ingest"): (CurriculumIngestAccepted, 202),
    ("POST", "/api/courses/{course_id}/curriculum/versions"): (CurriculumVersionOut, 201),
    (
        "POST",
        "/api/courses/{course_id}/curriculum/versions/{version_id}/candidates/{candidate_id}/review",
    ): (CurriculumCandidateOut, 200),
    ("POST", "/api/courses/{course_id}/curriculum/versions/{version_id}/publish"): (CurriculumPublishOut, 200),
    ("GET", "/api/courses/{course_id}/practice/exercises"): (list[ExerciseOut], 200),
    ("POST", "/api/practice/sessions"): (PracticeSessionOut, 201),
    ("POST", "/api/practice/sessions/{session_id}/attempts"): (PerformanceAttemptOut, 201),
    ("GET", "/api/practice/attempts/{attempt_id}"): (PerformanceAttemptOut, 200),
    ("POST", "/api/practice/attempts/{attempt_id}/speech"): (VoiceArtifactOut, 200),
    ("POST", "/api/recordings"): (RecordingOut, 201),
    ("GET", "/api/recordings/{recording_id}"): (RecordingOut, 200),
    ("POST", "/api/courses/{course_id}/documents"): (IngestAccepted, 202),
    ("POST", "/api/courses/{course_id}/documents/url"): (IngestAccepted, 202),
    ("GET", "/api/jobs/{job_id}"): (IngestJobOut, 200),
    ("POST", "/api/jobs/{job_id}/retry"): (IngestAccepted, 202),
    ("POST", "/api/jobs/{job_id}/cancel"): (IngestJobOut, 200),
    ("POST", "/api/nodes/{node_id}/drill"): (DrillOut, 201),
    ("POST", "/api/attempts/{attempt_id}/grade"): (GradeResult, 200),
    ("GET", "/api/quests/daily"): (QuestBoard, 200),
    ("GET", "/api/courses/{course_id}/search"): (SearchResults, 200),
    ("POST", "/api/courses/{course_id}/ask"): (AskAnswer, 200),
    ("GET", "/api/courses/{course_id}/path"): (CoursePath, 200),
    ("GET", "/api/courses/{course_id}/progress"): (ProgressAnalytics, 200),
    ("GET", "/api/courses/{course_id}/cost"): (CourseCost, 200),
    ("POST", "/api/admin/courses/{course_id}/reindex"): (ReindexAccepted, 202),
    ("GET", "/api/admin/courses/{course_id}/projection"): (ProjectionStatus, 200),
    ("GET", "/api/admin/courses/{course_id}/rejections"): (RejectionsPage, 200),
}


_RESPONSE_PAYLOADS: dict[type[BaseModel], dict[str, Any]] = {
    TokenResponse: {"access_token": "token", "token_type": "bearer", "user": _USER},
    PasswordResetRequested: {"message": "If that email is registered, a reset link is on its way."},
    UserOut: _USER,
    CourseOut: _COURSE,
    CourseList: {"courses": [_COURSE]},
    CourseDetail: {**_COURSE, "documents": [_DOCUMENT]},
    CharacterSheet: {
        "profile": {
            "user_id": _ID,
            "character_name": "Ada",
            "avatar_key": "owl",
            "archetype": "scholar",
            "skin_tone": "sand",
            "hair_style": "sweep",
            "hair_color": "chestnut",
            "outfit_color": "azure",
            "accessory": "none",
            "unlocked_perks": [],
            "created_at": _DT,
        },
        "level": 2,
        "total_exp": 1200,
        "exp_into_level": 200,
        "exp_for_next_level": 1030,
        "streak_days": 3,
        "stats": {"focus": 55, "memory": 48, "resilience": 45, "curiosity": 50},
        "perks": [
            {
                "id": "daily_momentum",
                "title": "Daily Momentum",
                "description": "Show one extra frontier quest on the Daily Quest board.",
                "cost": 1,
                "unlocked": False,
            }
        ],
        "achievements": [
            {
                "id": "first_drill",
                "title": "First Steps",
                "description": "Complete your first graded drill.",
                "progress": 1,
                "target": 1,
                "unlocked": True,
            }
        ],
        "available_perk_points": 2,
    },
    CampaignBriefingOut: {
        "course_id": _ID,
        "goal": "learn vectors",
        "target_outcome": "explain and apply vector projections",
        "proposal_version": 1,
        "tree_shape": {
            "playable_skills": 3,
            "branches": 1,
            "prerequisite_links": 2,
            "depth": 3,
            "depth_counts": {"0": 1, "1": 1, "2": 1},
            "starting_skills": [{"id": _NODE_ID, "title": "Vectors"}],
        },
        "outcome_coverage": {
            "outcome": "explain and apply vector projections",
            "terms": ["apply", "vector", "projections"],
            "matched_terms": ["vector"],
            "missing_terms": ["apply", "projections"],
            "coverage": 0.3333,
            "signal": "Some objective terms are visible; review the missing terms before expanding the campaign.",
        },
    },
    CampaignOutcomeEvaluationOut: {
        "course_id": _ID,
        "outcome": "explain and apply vector projections",
        "provider": "fake",
        "mode": "deterministic",
        "evaluated_skill_count": 3,
        "readiness": 0.6667,
        "matched_skills": [{"id": _NODE_ID, "title": "Vectors"}],
        "missing_capabilities": ["projections"],
        "side_quests": [
            {
                "capability": "projections",
                "title": "Find evidence for projections",
                "reason": "The generated tree does not clearly cover projections for this victory condition.",
                "source_query": (
                    "explain and apply vector projections; focus on projections; "
                    "include practical examples and assessment material"
                ),
                "action": "Find and approve a source focused on this capability, then ingest it to grow the campaign tree.",
            }
        ],
        "rationale": "The generated skills cover the vector part of the objective.",
    },
    CurriculumVersionOut: {
        "id": _ID,
        "course_id": _ID,
        "instrument": "violin",
        "slug": "violin-foundations",
        "title": "Violin Foundations",
        "version": 1,
        "status": "review",
        "compiler_version": "curriculum-compiler-v1",
        "node_count": 3,
        "candidate_count": 2,
        "rejected_count": 0,
        "created_at": _DT,
        "published_at": None,
    },
    CurriculumCandidateOut: {
        "id": _ID,
        "version_id": _ID,
        "prereq": "instrument-setup",
        "target": "bow-hold",
        "confidence": 0.9,
        "support": 1,
        "status": "accepted",
        "rationale": "Prerequisites: instrument-setup",
        "rejection_reason": None,
        "cycle_path": [],
        "evidence_count": 1,
    },
    CurriculumPublishOut: {
        "version_id": _ID,
        "course_id": _ID,
        "graph_version": 3,
        "node_count": 3,
        "edge_count": 2,
    },
    CurriculumProposalOut: {
        "id": _ID,
        "course_id": _ID,
        "goal": "learn vectors",
        "target_outcome": "explain and apply vector projections",
        "prior_knowledge": "basic algebra",
        "application_context": "robotics project",
        "proposal_version": 1,
        "supersedes_id": None,
        "learner_level": "beginner",
        "weekly_minutes": 120,
        "format_preference": "mixed",
        "provider": "fake",
        "status": "draft",
        "created_at": _DT,
        "sources": [
            {
                "id": _NODE_ID,
                "rank": 1,
                "title": "A guide to vectors",
                "url": "https://example.com/vectors",
                "domain": "example.com",
                "snippet": "A source about vectors.",
                "discovery_angle": "general",
                "published_at": None,
                "quality_score": 0.72,
                "quality_reasons": ["matches 1 goal term"],
                "policy_status": "review_required",
                "robots_url": "https://example.com/robots.txt",
                "robots_status": "not_checked",
                "license_status": "not_identified",
                "policy_reasons": [
                    "robots.txt has not been checked yet",
                    "license was not identified from search metadata",
                ],
                "policy_checked_at": None,
                "policy_acknowledged": False,
                "selected": False,
                "status": "proposed",
                "ingest_job_id": None,
                "ingest_error": None,
            }
        ],
    },
    CurriculumIngestAccepted: {
        "proposal_id": _ID,
        "course_id": _ID,
        "accepted": [{"source_id": _NODE_ID, "job_id": _ATTEMPT_ID, "status": "accepted", "error": None}],
    },
    DocumentSummary: _DOCUMENT,
    IngestAccepted: {"document": _DOCUMENT, "job_id": _ID, "deduplicated": False},
    IngestJobOut: {
        "id": _ID,
        "document_id": _ID,
        "course_id": _ID,
        "state": "extracting",
        "units_done": 4,
        "units_total": 10,
        "percent": 40.0,
        "stage_detail": {"chunks": 24, "failed_windows": 0},
        "error": None,
        "started_at": _DT,
        "finished_at": None,
    },
    GraphSnapshot: {
        "course_id": _ID,
        "graph_version": 2,
        "nodes": [_NODE],
        "edges": [
            {
                "id": "vectors->matrices",
                "source": _NODE_ID,
                "target": _ID,
                "confidence": 0.91,
                "support": 2,
                "rationale": "Vectors are used to define the target operation.",
                "sources": [_EVIDENCE],
            }
        ],
        "stats": {"total": 1, "locked": 0, "available": 1, "learning": 0, "decaying": 0, "mastered": 0},
    },
    DrillOut: {
        "attempt_id": _ATTEMPT_ID,
        "node_id": _NODE_ID,
        "node_title": "Vectors",
        "question": "What is a vector?",
        "question_type": "short_answer",
        "options": [],
        "code_language": None,
        "difficulty": 2,
        "sources": [_SOURCE],
    },
    GradeResult: {
        "attempt_id": _ATTEMPT_ID,
        "node_id": _NODE_ID,
        "score": 0.8,
        "verdict": "correct",
        "feedback": "Good explanation.",
        "points_hit": ["definition"],
        "points_missed": [],
        "exp_awarded": 25,
        "rescue_bonus_applied": False,
        "level_before": 1,
        "level_after": 1,
        "level_up": False,
        "account_level_before": 2,
        "account_level_after": 2,
        "account_level_up": False,
        "user_total_exp": 145,
        "progress": _PROGRESS,
        "unlocked_node_ids": [],
    },
    QuestBoard: {
        "date": "2026-08-13",
        "streak_days": 3,
        "total_reward_exp": 50,
        "quests": [
            {
                "node_id": _NODE_ID,
                "node_title": "Vectors",
                "course_id": _ID,
                "course_title": "Linear Algebra",
                "reason": "frontier",
                "overdue_days": 0.0,
                "proficiency": 0.35,
                "due_at": None,
                "reward_exp": 50,
            }
        ],
    },
    SearchResults: {
        "query": "vectors",
        "results": [
            {
                "node_id": _NODE_ID,
                "slug": "vectors",
                "title": "Vectors",
                "summary": "Representations of magnitude and direction.",
                "assessable": True,
                "depth": 0,
                "score": 1.0,
                "match": "both",
                "snippet": "A vector has magnitude and direction.",
                "source": _SOURCE,
            }
        ],
        "semantic": True,
    },
    AskAnswer: {
        "question": "what is a vector?",
        "answer": "A vector represents magnitude and direction.",
        "citations": [
            {
                "node_id": _NODE_ID,
                "node_title": "Vectors",
                "slug": "vectors",
                "chunk_id": _CHUNK_ID,
                "quote": "A vector has magnitude and direction.",
                "source": _SOURCE,
            }
        ],
        "retrieved": 1,
    },
    CoursePath: {
        "course_id": _ID,
        "steps": [
            {
                "order": 0,
                "node_id": _NODE_ID,
                "slug": "vectors",
                "title": "Vectors",
                "summary": "Representations of magnitude and direction.",
                "depth": 0,
                "difficulty": 2,
                "state": "available",
                "mastery": 0.4,
                "done": False,
            }
        ],
        "next_node_id": _NODE_ID,
        "completed": 0,
        "total": 1,
    },
    ProgressAnalytics: {
        "course_id": _ID,
        "total_skills": 4,
        "started_skills": 2,
        "mastered_skills": 1,
        "total_attempts": 3,
        "average_score": 0.8,
        "exp_earned": 120,
        "review_days": 2,
        "tracked_days": 3,
        "consistency": 0.6667,
        "mastery_trend": [
            {
                "date": "2026-08-12",
                "attempts": 1,
                "average_score": 1.0,
                "mastery": 0.1,
                "exp_earned": 50,
            }
        ],
        "source_coverage": [
            {
                "document_id": _ID,
                "filename": "linear-algebra.pdf",
                "skills_total": 4,
                "skills_started": 2,
                "attempts": 3,
            }
        ],
    },
    CourseCost: {
        "course_id": _ID,
        "total_calls": 1,
        "failed_calls": 0,
        "total_input_tokens": 100,
        "total_output_tokens": 50,
        "total_cost_usd": 0.01,
        "budget_usd": 5.0,
        "budget_remaining_usd": 4.99,
        "budget_exceeded": False,
        "by_role": [],
    },
    ExerciseOut: {
        "id": _ID,
        "course_id": _ID,
        "node_id": _NODE_ID,
        "slug": "stepwise-c-major",
        "title": "Stepwise C Major",
        "instructions": "Play four notes evenly.",
        "score_title": "Stepwise C Major",
        "score_format": "musicxml",
        "tempo_bpm": 120.0,
        "duration_beats": 4.0,
        "evaluator_version": "piano-dtw-v1",
        "difficulty": 2,
    },
    PracticeSessionOut: {
        "id": _ID,
        "course_id": _ID,
        "exercise_id": _NODE_ID,
        "status": "active",
        "created_at": _DT,
        "completed_at": None,
    },
    VoiceArtifactOut: {
        "attempt_id": _ID,
        "provider": "fake",
        "voice_key": "professor-cadenza",
        "format": "wav",
        "audio_base64": "UklGRgAAABdGTFNF",
        "spoken_text": "Stepwise C Major was a clean run. Next: raise the tempo.",
        "cache_key": "a1b2c3",
        "cached": False,
    },
    RecordingOut: {
        "id": _ID,
        "course_id": _ID,
        "attempt_id": None,
        "format": "webm",
        "byte_size": 5120,
        "content_sha256": "a" * 64,
        "duration_seconds": 3.2,
        "created_at": _DT,
        "deduplicated": False,
    },
    PerformanceAttemptOut: {
        "id": _ID,
        "session_id": _ID,
        "exercise_id": _NODE_ID,
        "status": "completed",
        "overall_score": 1.0,
        "alignment_confidence": 1.0,
        "exp_awarded": 100,
        "feedback_provider": "deterministic",
        "created_at": _DT,
        "metrics": {
            "evaluator_version": "piano-dtw-v1",
            "expected_note_count": 4,
            "observed_note_count": 4,
            "matched_note_count": 4,
            "missed_note_count": 0,
            "extra_note_count": 0,
            "pitch_accuracy": 1.0,
            "rhythm_accuracy": 1.0,
            "technique_accuracy": None,
            "position_error_count": 0,
            "intonation_accuracy": None,
            "intonation_deviation_cents": None,
            "tempo_bpm": 120.0,
            "tempo_deviation_percent": 0.0,
            "alignment_confidence": 1.0,
            "overall_score": 1.0,
            "low_confidence": False,
        },
        "feedback": {
            "persona": "Professor Cadenza",
            "tone": "celebratory",
            "summary": "Stepwise C Major was a clean, confident run at 100%.",
            "strengths": ["Your pitch is nearly flawless."],
            "corrections": [],
            "next_step": "Raise the tempo a little and press Stepwise C Major once more to lock it in.",
        },
    },
    ReindexAccepted: {"job_id": _ID, "course_id": _ID, "scope": "all", "deduplicated": False},
    ProjectionStatus: {
        "course_id": _ID,
        "graph_version": 2,
        "node_count": 1,
        "edge_count": 0,
        "chunk_count": 1,
        "neo4j_reachable": True,
        "projected_version": 2,
        "stale": False,
        "chroma_reachable": True,
        "vector_count": 1,
        "detail": None,
    },
    RejectionsPage: {
        "course_id": _ID,
        "total": 0,
        "by_reason": {},
        "limit": 50,
        "offset": 0,
        "rows": [],
    },
    ShareCreated: {
        "course_id": _ID,
        "url": "http://localhost:3000/share/abc123",
        "created_at": _DT,
    },
    ShareStatus: {"course_id": _ID, "shared": True, "created_at": _DT},
    SharePreview: {
        "course_id": _ID,
        "title": "Linear Algebra",
        "description": "A small course",
        "status": "ready",
        "node_count": 4,
        "edge_count": 3,
        "shared_by": "Dev",
        "created_at": _DT,
    },
    CourseLeaderboard: {
        "course_id": _ID,
        "cohort_size": 2,
        "entries": [
            {
                "display_name": "Dev",
                "level": 3,
                "total_exp": 220,
                "streak_days": 4,
                "mastered_count": 2,
                "started_count": 3,
                "me": True,
            }
        ],
        "my_rank": 1,
    },
}


_FRONTEND_MODELS = {
    TokenResponse: "TokenResponse",
    CharacterSheet: "CharacterSheet",
    PasswordResetRequested: "PasswordResetRequested",
    UserOut: "User",
    CourseOut: "Course",
    CourseDetail: "CourseDetail",
    CampaignBriefingOut: "CampaignBriefing",
    CampaignOutcomeEvaluationOut: "CampaignOutcomeEvaluation",
    CurriculumProposalOut: "CurriculumProposal",
    CurriculumVersionOut: "CurriculumVersion",
    CurriculumCandidateOut: "CurriculumCandidate",
    CurriculumPublishOut: "CurriculumPublishResult",
    ExerciseOut: "Exercise",
    PracticeSessionOut: "PracticeSession",
    PerformanceAttemptOut: "PerformanceAttempt",
    RecordingOut: "Recording",
    VoiceArtifactOut: "VoiceArtifact",
    CurriculumIngestAccepted: "CurriculumIngestAccepted",
    IngestAccepted: "IngestAccepted",
    IngestJobOut: "IngestJob",
    GraphSnapshot: "GraphSnapshot",
    DrillOut: "Drill",
    GradeResult: "GradeResult",
    QuestBoard: "QuestBoard",
    SearchResults: "SearchResults",
    AskAnswer: "AskAnswer",
    CoursePath: "CoursePath",
    ProgressAnalytics: "ProgressAnalytics",
    CourseCost: "CourseCost",
    ReindexAccepted: "ReindexAccepted",
    ProjectionStatus: "ProjectionStatus",
    RejectionsPage: "RejectionsPage",
    ShareCreated: "ShareCreated",
    ShareStatus: "ShareStatus",
    SharePreview: "SharePreview",
    CourseLeaderboard: "CourseLeaderboard",
}



def _openapi_operation(endpoint: tuple[str, str]) -> dict[str, Any]:
    method, path = endpoint
    return OPENAPI["paths"][path][method.lower()]


def _frontend_interfaces() -> dict[str, tuple[str | None, set[str]]]:
    """Read only top-level fields from exported TS interfaces.

    The project intentionally has no TypeScript test runner. Keeping this parser
    tiny and limited to the flat interface declarations makes the mirror check
    dependency-free while still failing on renamed, added, or removed wire keys.
    """
    lines = FRONTEND_TYPES.read_text(encoding="utf-8").splitlines()
    start_pattern = re.compile(r"^export interface (\w+)(?: extends (\w+))? \{")
    field_pattern = re.compile(r"^\s{2,}([A-Za-z_]\w*)\??\s*:")
    interfaces: dict[str, tuple[str | None, set[str]]] = {}
    index = 0
    while index < len(lines):
        match = start_pattern.match(lines[index])
        if match:
            fields: set[str] = set()
            index += 1
            while index < len(lines) and lines[index].strip() != "}":
                field = field_pattern.match(lines[index])
                if field:
                    fields.add(field.group(1))
                index += 1
            interfaces[match.group(1)] = (match.group(2), fields)
        index += 1
    return interfaces


def _frontend_fields(name: str, interfaces: dict[str, tuple[str | None, set[str]]]) -> set[str]:
    base, fields = interfaces[name]
    if base is None:
        return set(fields)
    return set(fields) | _frontend_fields(base, interfaces)


@pytest.mark.parametrize("endpoint, expected", _ROUTE_CONTRACT.items())
def test_learner_routes_keep_the_documented_response_model_and_status(
    endpoint: tuple[str, str], expected: tuple[Any, int]
) -> None:
    response_model, status_code = expected
    operation = _openapi_operation(endpoint)
    response = operation["responses"].get(str(status_code))
    assert response is not None, f"missing {status_code} response for {endpoint[0]} {endpoint[1]}"
    schema = response["content"]["application/json"]["schema"]
    if get_origin(response_model) is list:
        item_model = get_args(response_model)[0]
        assert schema["type"] == "array"
        assert schema["items"]["$ref"] == f"#/components/schemas/{item_model.__name__}"
    else:
        assert schema["$ref"] == f"#/components/schemas/{response_model.__name__}"


@pytest.mark.parametrize("model, payload", _RESPONSE_PAYLOADS.items())
def test_response_fixtures_validate_against_backend_models(model: type[BaseModel], payload: dict[str, Any]) -> None:
    validated = TypeAdapter(model).validate_python(payload)
    assert isinstance(validated, model)


# @spec OPS-CONTRACT-001, OPS-CONTRACT-002, OPS-CONTRACT-003
def test_frontend_mirror_contains_exact_backend_response_fields() -> None:
    interfaces = _frontend_interfaces()
    missing_interfaces = sorted(set(_FRONTEND_MODELS.values()) - set(interfaces))
    assert not missing_interfaces, f"missing frontend interfaces: {missing_interfaces}"

    mismatches: list[str] = []
    for model, frontend_name in _FRONTEND_MODELS.items():
        backend_fields = set(model.model_fields)
        frontend_fields = _frontend_fields(frontend_name, interfaces)
        if backend_fields != frontend_fields:
            mismatches.append(
                f"{model.__name__} -> {frontend_name}: backend={sorted(backend_fields)}, "
                f"frontend={sorted(frontend_fields)}"
            )
    assert not mismatches, "API contract field drift:\n" + "\n".join(mismatches)


def test_nested_document_summary_is_executable_too() -> None:
    """The course/detail seam must not silently lose source provenance fields."""
    validated = TypeAdapter(DocumentSummary).validate_python(_DOCUMENT)
    assert validated.source_uri is None
    assert set(DocumentSummary.model_fields) == {
        "id",
        "filename",
        "source_type",
        "source_uri",
        "page_count",
        "chunk_count",
        "created_at",
    }


def test_curriculum_candidate_list_has_an_array_response_contract() -> None:
    operation = OPENAPI["paths"][
        "/api/courses/{course_id}/curriculum/versions/{version_id}/candidates"
    ]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["$ref"] == "#/components/schemas/CurriculumCandidateOut"


def test_practice_exercise_list_has_an_array_response_contract() -> None:
    operation = OPENAPI["paths"]["/api/courses/{course_id}/practice/exercises"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["$ref"] == "#/components/schemas/ExerciseOut"


def test_recording_content_and_delete_routes_exist() -> None:
    """The binary content and 204 delete endpoints do not fit the JSON route
    inventory above; assert their presence and status codes separately."""
    content_operation = OPENAPI["paths"]["/api/recordings/{recording_id}/content"]["get"]
    assert "200" in content_operation["responses"]
    delete_operation = OPENAPI["paths"]["/api/recordings/{recording_id}"]["delete"]
    assert "204" in delete_operation["responses"]
