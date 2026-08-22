"""Every external service this app can talk to, in one table.

The seams already existed -- LLM, embeddings, voice, email, research, storage,
OAuth, webhooks -- but they were described in eight different places, and the
only way to find out what a key was called was to read `config.py`. That is the
gap this module closes: one declarative list of what can be turned on, which
environment variables turn it on, and what happens while it is off.

Two rules the whole file exists to enforce:

**Off is a supported state, not a broken one.** Every integration here has a
working fallback, and the fallback is a real implementation rather than a stub
that raises. The entire product runs, and is tested, with every one of these
switched off.

**Turning one on is configuration, never code.** If enabling a provider needs an
edit to a module, that is a bug in the seam. So this table is also a checklist:
anything listed here should come alive by setting the variables named here and
restarting.

Nothing in this module reads a secret's *value* into anything it returns. It
reports presence, never content, so it is safe to expose over HTTP and safe to
print in a terminal someone is screen-sharing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.config import Settings, get_settings

__all__ = [
    "INTEGRATIONS",
    "Integration",
    "IntegrationStatus",
    "integration_statuses",
    "missing_for_deployment",
]


@dataclass(frozen=True, slots=True)
# @spec OPS-INTEG-001, OPS-INTEG-007
class Integration:
    key: str
    title: str
    # One line: what the product gains by turning this on.
    purpose: str
    # What happens while it is off. Never "it breaks".
    fallback: str
    # The environment variables that must be non-empty for this to work.
    credentials: tuple[str, ...]
    # Variables worth knowing about but not required.
    options: tuple[str, ...]
    # Where to get the credential.
    provider_url: str
    # True when the operator has asked for this integration at all.
    selected: Callable[[Settings], bool]
    # The credentials that are actually present, as (name, present) pairs.
    present: Callable[[Settings], tuple[tuple[str, bool], ...]]
    # Whether a deployed environment must have this configured.
    required_when_deployed: bool = False
    # How the selector is set, for the message telling someone how to enable it.
    enable_hint: str = ""


def _pairs(settings: Settings, names: tuple[str, ...]) -> tuple[tuple[str, bool], ...]:
    """Presence only. The value never leaves this function."""
    return tuple((name, bool(getattr(settings, name.lower(), ""))) for name in names)


def _gemini_credentials(settings: Settings) -> tuple[tuple[str, bool], ...]:
    """Gemini needs one credential somewhere, not one per lane.

    A key against a single lane is a complete configuration: that lane runs on
    Gemini and the rest run on the deterministic floor, which is a supported state
    rather than a broken one. Requiring all three would report a deployment that
    is deliberately paying for one lane as misconfigured, and "misconfigured" is
    the word this table reserves for something an operator did not intend.

    Which lane is served by what is a separate question, answered by the provider
    report rather than by a presence check.
    """
    from app.llm.registry import LANES

    return (("GEMINI_API_KEY", any(settings.gemini_key_for(lane) for lane in LANES)),)


INTEGRATIONS: tuple[Integration, ...] = (
    Integration(
        key="anthropic",
        title="Anthropic",
        purpose="Real language models for graph extraction, grading, examiner feedback, and live coaching.",
        fallback="A deterministic word-matching provider that exercises every prompt, schema, and ledger path for free.",
        credentials=("ANTHROPIC_API_KEY",),
        options=(),
        provider_url="https://console.anthropic.com/settings/keys",
        selected=lambda s: s.llm_provider.lower() == "anthropic",
        present=lambda s: _pairs(s, ("ANTHROPIC_API_KEY",)),
        enable_hint="LLM_PROVIDER=anthropic",
    ),
    Integration(
        key="openai",
        title="OpenAI",
        purpose="An alternative language model, and the only real embedding provider wired up.",
        fallback="Fake embeddings are hashed bag-of-words: directionally sane, so retrieval tests mean something.",
        credentials=("OPENAI_API_KEY",),
        options=("EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS"),
        provider_url="https://platform.openai.com/api-keys",
        selected=lambda s: "openai" in {s.llm_provider.lower(), s.embedding_provider.lower()},
        present=lambda s: _pairs(s, ("OPENAI_API_KEY",)),
        enable_hint="LLM_PROVIDER=openai or EMBEDDING_PROVIDER=openai",
    ),
    Integration(
        key="gemini",
        title="Google Gemini",
        purpose=(
            "An alternative language model and embedding provider, and the only credentialed "
            "provider that streams -- which is what lets the live coach speak from a model."
        ),
        fallback=(
            "The deterministic provider, which streams too: word by word, so the incremental "
            "render and barge-in paths are exercised for free. Applies per workload lane, so a "
            "lane with no key runs on it while the paid lanes run on Gemini."
        ),
        credentials=("GEMINI_API_KEY",),
        options=(
            "GEMINI_API_KEY_INGEST",
            "GEMINI_API_KEY_TUTOR",
            "GEMINI_API_KEY_LIVE",
            "GEMINI_BASE_URL",
            "GEMINI_TIMEOUT_SECONDS",
            "GEMINI_MAX_RETRIES",
            "GEMINI_EMBEDDING_MODEL",
            "EMBEDDING_DIMENSIONS",
        ),
        provider_url="https://aistudio.google.com/apikey",
        selected=lambda s: "gemini" in {s.llm_provider.lower(), s.embedding_provider.lower()},
        present=_gemini_credentials,
        enable_hint="LLM_PROVIDER=gemini or EMBEDDING_PROVIDER=gemini",
    ),
    Integration(
        key="elevenlabs",
        title="ElevenLabs",
        purpose="The examiner's actual voice, for both post-take feedback and live coaching.",
        fallback="A deterministic silence WAV, plus the spoken text on every response so the browser speaks it itself.",
        credentials=("ELEVENLABS_API_KEY",),
        options=("ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "ELEVENLABS_STREAMING_MODEL_ID"),
        provider_url="https://elevenlabs.io/app/settings/api-keys",
        selected=lambda s: s.voice_provider.lower() == "elevenlabs",
        present=lambda s: _pairs(s, ("ELEVENLABS_API_KEY",)),
        enable_hint="VOICE_PROVIDER=elevenlabs",
    ),
    Integration(
        key="exa",
        title="Exa",
        purpose="Live web search when turning a learning goal into a reviewable set of source material.",
        fallback="Deterministic example results, so the proposal and approval flow is demoable without a search bill.",
        credentials=("EXA_API_KEY",),
        options=("RESEARCH_MAX_RESULTS", "RESEARCH_TIMEOUT_SECONDS"),
        provider_url="https://dashboard.exa.ai/api-keys",
        selected=lambda s: s.research_provider.lower() == "exa",
        present=lambda s: _pairs(s, ("EXA_API_KEY",)),
        enable_hint="RESEARCH_PROVIDER=exa",
    ),
    Integration(
        key="resend",
        title="Resend",
        purpose="Delivers password-reset email.",
        fallback="The reset link is logged instead of sent, which is what makes recovery testable locally.",
        credentials=("RESEND_API_KEY",),
        options=("EMAIL_FROM",),
        provider_url="https://resend.com/api-keys",
        selected=lambda s: s.email_provider.lower() == "resend",
        present=lambda s: _pairs(s, ("RESEND_API_KEY",)),
        required_when_deployed=True,
        enable_hint="EMAIL_PROVIDER=resend",
    ),
    Integration(
        key="gcs",
        title="Google Cloud Storage",
        purpose="Shared object storage for uploaded sources and preserved takes.",
        fallback="The local filesystem under UPLOAD_DIR. Fine on one machine; ephemeral on a managed host.",
        credentials=("GCS_BUCKET",),
        options=("GCS_PREFIX",),
        provider_url="https://console.cloud.google.com/storage",
        selected=lambda s: s.storage_backend.lower() == "gcs",
        present=lambda s: _pairs(s, ("GCS_BUCKET",)),
        required_when_deployed=True,
        enable_hint="STORAGE_BACKEND=gcs",
    ),
    Integration(
        key="google_oauth",
        title="Google OAuth",
        purpose="Sign in with Google.",
        fallback="Email and password sign-in, which is always available.",
        credentials=("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"),
        options=("GOOGLE_OAUTH_REDIRECT_URI", "FRONTEND_URL"),
        provider_url="https://console.cloud.google.com/apis/credentials",
        # Unlike the others there is no selector: configuring it is enabling it.
        selected=lambda s: bool(s.google_oauth_client_id or s.google_oauth_client_secret),
        present=lambda s: _pairs(s, ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")),
        required_when_deployed=True,
        enable_hint="GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET",
    ),
    Integration(
        key="n8n_inbound",
        title="n8n (inbound)",
        purpose="Lets n8n call the app: session completed, feedback requested, nightly quest refresh.",
        fallback="The endpoints answer 503 unless DEV_WEBHOOKS_ENABLED is on, which accepts unsigned local calls.",
        credentials=("WEBHOOK_SECRET",),
        options=("DEV_WEBHOOKS_ENABLED",),
        provider_url="https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/",
        selected=lambda s: bool(s.webhook_secret) or s.dev_webhooks_enabled,
        present=lambda s: _pairs(s, ("WEBHOOK_SECRET",)),
        required_when_deployed=True,
        enable_hint="WEBHOOK_SECRET=<shared secret>",
    ),
    Integration(
        key="n8n_outbound",
        title="n8n (outbound)",
        purpose="The app POSTs its own events to n8n, so a workflow can react to a finished take rather than poll.",
        fallback="Nothing is emitted. No code path waits on it, so the product behaves identically.",
        credentials=("N8N_WEBHOOK_URL",),
        options=("WEBHOOK_SECRET", "N8N_TIMEOUT_SECONDS"),
        provider_url="https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/",
        selected=lambda s: bool(s.n8n_webhook_url),
        present=lambda s: _pairs(s, ("N8N_WEBHOOK_URL",)),
        enable_hint="N8N_WEBHOOK_URL=https://<your n8n>/webhook/learn-any-instrument",
    ),
)


@dataclass(frozen=True, slots=True)
class IntegrationStatus:
    key: str
    title: str
    purpose: str
    fallback: str
    # off      -- not selected; the fallback is in use
    # live     -- selected and every credential present
    # misconfigured -- selected but a credential is missing
    mode: str
    selected: bool
    # What this integration needs, always. Reading it does not imply a problem.
    requires: tuple[str, ...]
    # What it needs and does not have -- empty unless it was actually asked for,
    # because an unset key on an integration nobody turned on is not missing.
    missing: tuple[str, ...]
    options: tuple[str, ...]
    provider_url: str
    enable_hint: str
    required_when_deployed: bool

    @property
    def ready(self) -> bool:
        return self.mode != "misconfigured"


# @spec OPS-INTEG-002, OPS-INTEG-003, OPS-INTEG-004, OPS-INTEG-005
def integration_statuses(settings: Settings | None = None) -> tuple[IntegrationStatus, ...]:
    """What is on, what is off, and what is asked for but not configured.

    Reports presence of credentials, never their values, so this is safe to
    serve over HTTP and safe to print.
    """
    resolved = settings or get_settings()
    statuses: list[IntegrationStatus] = []
    for integration in INTEGRATIONS:
        selected = integration.selected(resolved)
        absent = tuple(name for name, present in integration.present(resolved) if not present)
        if not selected:
            mode = "off"
        elif absent:
            mode = "misconfigured"
        else:
            mode = "live"
        statuses.append(
            IntegrationStatus(
                key=integration.key,
                title=integration.title,
                purpose=integration.purpose,
                fallback=integration.fallback,
                mode=mode,
                selected=selected,
                requires=integration.credentials,
                missing=absent if selected else (),
                options=integration.options,
                provider_url=integration.provider_url,
                enable_hint=integration.enable_hint,
                required_when_deployed=integration.required_when_deployed,
            )
        )
    return tuple(statuses)


# @spec OPS-CONFIG-007
def missing_for_deployment(settings: Settings | None = None) -> tuple[str, ...]:
    """Integrations a deployed environment needs that are not live.

    Advisory: `Settings` already refuses to start with `DEPLOYED=true` and a
    development default in place. This is the same question asked early enough
    to answer before a deploy rather than during one.
    """
    return tuple(
        f"{status.title} ({status.enable_hint})"
        for status in integration_statuses(settings)
        if status.required_when_deployed and status.mode != "live"
    )
