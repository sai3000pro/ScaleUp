"""Every model must be imported here.

Alembic's autogenerate only sees tables registered on `Base.metadata`, and a
model that is never imported is never registered -- the classic way a migration
silently omits a table.
"""

from app.db.base import Base
from app.models.attempt import Attempt, Question
from app.models.auth import OAuthAccount, OAuthExchangeCode, OAuthState, PasswordResetToken, RefreshSession
from app.models.character import CharacterProfile
from app.models.coach import CoachSession, CoachUtterance
from app.models.course import Course
from app.models.curriculum import CurriculumProposal, CurriculumSource
from app.models.curriculum_graph import (
    CurriculumEvidence,
    CurriculumNode,
    CurriculumReview,
    CurriculumVersion,
    Instrument,
    PrerequisiteCandidate,
    SkillDefinition,
)
from app.models.document import Chunk, Document, DocumentPage, IngestJob
from app.models.llm_call import LlmCall
from app.models.performance import (
    Exercise,
    PerformanceAttempt,
    PerformanceMetricBundle,
    PracticeSession,
    Recording,
    ScoreAsset,
    StoredVoiceArtifact,
)
from app.models.progress import NodeProgress
from app.models.share import CourseShare
from app.models.skill import SkillEdge, SkillEdgeRejection, SkillNode
from app.models.user import User
from app.models.webhook import WebhookEvent

__all__ = [
    "Base",
    "Attempt",
    "OAuthAccount",
    "OAuthExchangeCode",
    "OAuthState",
    "PasswordResetToken",
    "RefreshSession",
    "Chunk",
    "CharacterProfile",
    "CoachSession",
    "CoachUtterance",
    "Course",
    "CurriculumProposal",
    "CurriculumSource",
    "CurriculumEvidence",
    "CurriculumNode",
    "CurriculumReview",
    "CurriculumVersion",
    "Instrument",
    "PrerequisiteCandidate",
    "SkillDefinition",
    "Document",
    "DocumentPage",
    "IngestJob",
    "LlmCall",
    "NodeProgress",
    "Exercise",
    "PerformanceAttempt",
    "PerformanceMetricBundle",
    "PracticeSession",
    "Recording",
    "ScoreAsset",
    "StoredVoiceArtifact",
    "CourseShare",
    "Question",
    "SkillEdge",
    "SkillEdgeRejection",
    "SkillNode",
    "User",
    "WebhookEvent",
]
