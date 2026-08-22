"""Single source of truth for environment configuration.

Every module reads settings from here rather than touching os.environ, so the
full set of knobs is discoverable in one place and typos fail at import rather
than at 3am inside a Celery task.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# repo_root/backend/app/config.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]

# Kept as a named constant so the startup check can recognise it. If you change
# this string, change it in .env.example too.
PLACEHOLDER_JWT_SECRET = "change-me-before-you-use-this-anywhere-real"


# @spec OPS-CONFIG-001, OPS-CONFIG-002, OPS-CONFIG-006, OPS-CONFIG-007
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── datastores ────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://la:la@localhost:5433/learn_anything"
    sync_database_url: str = "postgresql+psycopg://la:la@localhost:5433/learn_anything"

    celery_broker_url: str = "redis://localhost:6380/0"
    celery_result_backend: str = "redis://localhost:6380/1"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "learnanything"

    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # ── auth ──────────────────────────────────────────────────────────────
    jwt_secret: str = PLACEHOLDER_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 24
    refresh_token_ttl_days: int = 30
    refresh_cookie_name: str = "learn_anything_refresh"

    # Enables POST /api/auth/dev-login, which hands out a token for the seeded
    # dev user without a password. The route is not registered at all when this
    # is off -- better than a runtime check, because the endpoint genuinely does
    # not exist rather than merely refusing.
    dev_auth_enabled: bool = False

    # Password recovery and OAuth redirect targets. Keep the frontend URL
    # explicit in managed cloud deployments; it is also used to prevent open
    # redirects after Google returns.
    frontend_url: str = "http://localhost:3000"
    password_reset_ttl_minutes: int = 30
    oauth_state_ttl_minutes: int = 10
    oauth_exchange_code_ttl_minutes: int = 2

    # Email uses the Resend HTTP API in production. The fake provider logs a
    # development-only reset link and never makes a network request.
    email_provider: str = "fake"
    resend_api_key: str = ""
    email_from: str = "Learn-Any-Instrument <noreply@example.com>"

    # Google OAuth is opt-in until these credentials are configured.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Set this in any environment that is not a developer's laptop. It turns the
    # two settings above from conveniences into hard errors: a deployed app must
    # not run on the committed JWT secret, and must not serve dev-login.
    #
    # This exists because both failure modes are SILENT. A placeholder secret
    # works perfectly -- until someone reads it in the public repo and forges a
    # token for any user id. Nothing surfaces that at deploy time, so the check
    # has to be explicit.
    deployed: bool = False

    @model_validator(mode="after")
    def _resolve_upload_dir(self) -> Settings:
        """Make `upload_dir` absolute, anchored to the repo root."""
        if not self.upload_dir.is_absolute():
            object.__setattr__(self, "upload_dir", (REPO_ROOT / self.upload_dir).resolve())
        return self

    @model_validator(mode="after")
    # @spec ACCESS-AUTH-008, OPS-CONFIG-003, OPS-CONFIG-004, OPS-STORE-003
    def _reject_development_defaults_when_deployed(self) -> Settings:
        if self.deployed:
            problems: list[str] = []
            if self.jwt_secret == PLACEHOLDER_JWT_SECRET:
                problems.append("JWT_SECRET is still the committed placeholder; generate a real one")
            if self.dev_auth_enabled:
                problems.append("DEV_AUTH_ENABLED must be false when DEPLOYED=true")
            if self.email_provider == "fake":
                problems.append("EMAIL_PROVIDER must not be fake when DEPLOYED=true")
            if not self.google_oauth_client_id or not self.google_oauth_client_secret:
                problems.append("Google OAuth credentials must be configured when DEPLOYED=true")
            if self.url_fetch_allow_private_hosts:
                problems.append(
                    "URL_FETCH_ALLOW_PRIVATE_HOSTS must be false when DEPLOYED=true; "
                    "it disables the SSRF address check and makes the cloud metadata "
                    "endpoint reachable through the URL ingest form"
                )
            if self.storage_backend != "gcs":
                problems.append("STORAGE_BACKEND must be gcs when DEPLOYED=true; local uploads are ephemeral")
            if self.storage_backend == "gcs" and not self.gcs_bucket:
                problems.append("GCS_BUCKET is required when STORAGE_BACKEND=gcs")
            if not self.webhook_secret:
                problems.append("WEBHOOK_SECRET must be set when DEPLOYED=true; n8n webhooks would be unauthenticated")
            if "localhost" in self.cors_origin_regex or "127.0.0.1" in self.cors_origin_regex:
                problems.append(
                    "CORS_ORIGIN_REGEX still allows loopback origins when DEPLOYED=true; "
                    "set an explicit production origin allowlist"
                )
            if problems:
                raise ValueError("refusing to start: " + "; ".join(problems))
        return self

    # ── llm ───────────────────────────────────────────────────────────────
    # "fake" is the default on purpose: the whole ingestion and grading loop
    # runs and is testable with no API keys and no spend. Switch to "anthropic"
    # or "openai" once keys are in .env.
    llm_provider: str = "fake"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # One credential per workload lane, each falling back to GEMINI_API_KEY.
    # Separate keys are what stop a quota exhausted while compiling a curriculum
    # from silencing a learner's live coach: the lanes bill independently.
    gemini_api_key_ingest: str = ""
    gemini_api_key_tutor: str = ""
    gemini_api_key_live: str = ""
    # Google's OpenAI-compatible surface, for the role registry's structured and
    # streamed text calls. Empty follows the provider's own default; set it to
    # reach a proxy or to pin an API version.
    gemini_base_url: str = ""
    # How long a learner waits before the deterministic tree is served instead.
    gemini_timeout_seconds: float = 45.0
    gemini_max_retries: int = 1
    # The Live API is a different seam on the same credential: bidirectional audio
    # over a WebSocket, which the OpenAI-compatible surface does not carry.
    gemini_live_model: str = "models/gemini-2.0-flash-exp"

    def gemini_key_for(self, lane: str) -> str:
        """The credential serving one workload lane, or the shared one."""
        return getattr(self, f"gemini_api_key_{lane}", "") or self.gemini_api_key

    def gemini_lanes_without_a_key(self) -> tuple[str, ...]:
        """Lanes that would reach the provider with no credential at all.

        Checked at startup rather than on first use: a lane whose key is missing
        fails only when something routes to it, and the live coach is the lane
        most likely to be exercised first by a learner rather than by a developer.
        """
        from app.llm.registry import LANES

        return tuple(lane for lane in LANES if not self.gemini_key_for(lane))

    embedding_provider: str = "fake"
    embedding_model: str = "text-embedding-3-small"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 1536

    # A course-wide ceiling for billable LLM and embedding calls. The fake
    # providers estimate to $0 and therefore keep the entire offline loop free.
    # Set COURSE_LLM_BUDGET_USD per environment; this is deliberately not a
    # per-request limit because a textbook ingest is many calls in one course.
    course_llm_budget_usd: Decimal = Decimal("5.00")

    # ── pipeline ──────────────────────────────────────────────────────────
    #
    # `local` keeps Docker development and offline tests self-contained. Cloud
    # Run must use `gcs`: its writable filesystem is ephemeral, while the API
    # and Celery worker need to see the same textbook bytes across instances.
    storage_backend: str = "local"
    gcs_bucket: str = ""
    gcs_prefix: str = "learn-anything/sources"

    # Anchored to the repo root by `_resolve_upload_dir` below, because a
    # relative value here resolves against the CURRENT WORKING DIRECTORY. The
    # API is started from `backend/`, Celery from `backend/`, and the scripts
    # from the repo root -- so `./uploads` silently produced two different
    # directories, and a worker could not find the file the API had just
    # written. It also slipped past a `.gitignore` that only listed
    # `backend/uploads/`.
    upload_dir: Path = REPO_ROOT / "backend" / "uploads"
    pipeline_version: str = "1"
    chunk_tokens: int = 800
    chunk_overlap_tokens: int = 120
    extract_chunks_per_window: int = 6
    embed_batch_size: int = 64
    log_level: str = "INFO"

    # Split each outline section on the concept boundaries the book itself marks
    # ("Definition:", "Theorem:"). Off by default, and the reason is measured
    # rather than cautious: on CO 250 it does exactly what it should to the
    # NODES -- 44 -> 142, so "The KKT Theorem" stops being one node covering
    # seven separate skills -- but the prerequisite pass does not yet scale to
    # the graph it produces. That pass sends the whole skill vocabulary with
    # every section, so 135 skills x 135 sections lets a title like "Feasible
    # solution", which genuinely appears in most sections of an optimisation
    # textbook, collect 62 outbound edges. Measured on CO 250:
    #
    #     off  44 nodes   recall 0.397   precision 0.551
    #     on  142 nodes   recall 0.280   precision 0.157
    #
    # A wrong prerequisite locks a learner out of material they are ready for,
    # so shipping that trade by default would be a regression however much
    # better the node granularity is. Turn this on once the forward pass filters
    # candidates by how distinctive a title is, instead of matching all of them.
    segment_sections: bool = False

    # Ask a model to write each node's caption instead of taking the best
    # sentence `app/ingestion/summarise.py` can find in the node's own text.
    #
    # `None` means "follow the provider", which is the honest default in both
    # directions: with `LLM_PROVIDER=fake` there is no model worth asking (the
    # fake's word matcher is strictly worse than the deterministic summariser,
    # and a no-key run should still get the good captions), and with a real
    # provider configured a caption is a cheap call on the one string a learner
    # reads most often. Set it explicitly to measure one path against the other.
    summarise_nodes: bool | None = None

    @field_validator("summarise_nodes", mode="before")
    @classmethod
    def _parse_summarise_nodes(cls, v: object) -> object:
        if v == "" or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    def node_summaries_via_llm(self) -> bool:
        if self.summarise_nodes is None:
            return self.llm_provider != "fake"
        return self.summarise_nodes
    # How many outline entries a single document must yield before its own table
    # of contents is trusted as that document's structure. Below it, that
    # document alone falls back to LLM map/reduce extraction -- per document, not
    # per course; see `ingest_pipeline.extract_graph`.
    #
    # A setting rather than a constant because the right value is an empirical
    # question that changed the moment HTML landed. Four entries is a reasonable
    # floor for a textbook and roughly the point at which a PDF outline stops
    # being "Title Page / Copyright / Contents". A three-heading web article is a
    # genuinely different case, and the only way to find out whether it is better
    # served by its own thin outline or by the LLM is to measure both.
    min_toc_entries: int = 4

    # ── url ingestion ─────────────────────────────────────────────────────
    url_fetch_timeout_seconds: float = 15.0
    url_fetch_max_bytes: int = 10 * 1024 * 1024
    # Every hop is re-checked in full, so this is a loop bound rather than a
    # trust budget. Three covers http->https, bare->www, and one canonical
    # redirect, which is what real articles use.
    url_fetch_max_redirects: int = 3
    url_fetch_user_agent: str = "Learn-Any-Instrument/0.1 (+https://github.com/; personal study tool)"

    # Turns OFF the SSRF address check. Local development only -- it exists so a
    # docs server on 127.0.0.1 can be ingested, and it is exactly the switch that
    # makes `http://169.254.169.254/latest/meta-data/` fetchable. Rejected at
    # startup when DEPLOYED is true, alongside the other two.
    url_fetch_allow_private_hosts: bool = False

    # ── goal-to-curriculum research ───────────────────────────────────────
    # Fake is the default so proposal generation remains deterministic and free
    # in development. Set RESEARCH_PROVIDER=exa and EXA_API_KEY to enable live
    # bounded search; approval is still required before URL ingestion.
    research_provider: str = "fake"
    exa_api_key: str = ""
    research_max_results: int = 8
    research_timeout_seconds: float = 12.0

    # ── voice ─────────────────────────────────────────────────────────────
    # "fake" is the default on purpose: the demo's spoken-feedback endpoint
    # returns a deterministic silence WAV with no key, and the response always
    # carries the spoken text so the frontend can fall back to browser TTS.
    # How slowly the fake provider streams. Non-zero so the incremental render
    # path is actually exercised in development; set to 0 in CI so tests do not
    # pay for realism they cannot observe.
    fake_stream_delay_seconds: float = 0.02
    # A first token later than this means the learner has started playing again,
    # so the utterance is abandoned in favour of the deterministic sentence.
    coach_first_token_timeout_seconds: float = 1.5
    coach_utterance_timeout_seconds: float = 6.0
    coach_take_ttl_seconds: int = 30

    voice_provider: str = "fake"
    elevenlabs_api_key: str = ""
    # Which ElevenLabs voice speaks. Empty uses the provider module's default.
    # Changing it changes the voice a learner hears, and it feeds the voice
    # artifact cache key, so an existing cache is invalidated by design.
    elevenlabs_voice_id: str = ""
    # Flash is the low-latency model and the right default for a live coach;
    # multilingual v2 is better for the post-take clip. Both are overridable
    # without touching code.
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_streaming_model_id: str = "eleven_flash_v2_5"

    # ── webhooks (n8n) ────────────────────────────────────────────────────
    # HMAC-SHA256 shared secret that signs every n8n webhook payload
    # (`X-Webhook-Signature: sha256=<hex>` over the raw request body). Empty by
    # default so local development needs no setup; when empty the webhook
    # endpoints are only callable with DEV_WEBHOOKS_ENABLED=true and otherwise
    # answer 503 "webhooks not configured".
    webhook_secret: str = ""
    # Where the backend POSTs its own events, so n8n can react to a finished
    # take rather than polling for one. Empty means the outbound direction is
    # off entirely -- nothing is sent, nothing is retried, and no code path
    # waits on it. The inbound direction (n8n calling us) is independent and
    # controlled by WEBHOOK_SECRET above.
    n8n_webhook_url: str = ""
    n8n_timeout_seconds: float = 5.0
    # Lets the fake webhook runner and local tests exercise the webhook
    # contract without a shared secret. The deployed validator rejects
    # DEPLOYED=true with an empty WEBHOOK_SECRET, so this cannot silently
    # become a production bypass.
    dev_webhooks_enabled: bool = False

    # ── cors ──────────────────────────────────────────────────────────────
    # A regex rather than a list: Next.js silently falls back to the next free
    # port when 3000 is taken, and browser tooling reaches the dev server on
    # 127.0.0.1 rather than localhost. Pinning exact origins turns either of
    # those into a CORS failure that reads like a broken API.
    #
    # Loopback only. This is a development convenience and must be replaced with
    # an explicit origin list before anything is deployed.
    cors_origin_regex: str = r"http://(localhost|127\.0\.0\.1)(:\d+)?"

    def resolved_upload_dir(self) -> Path:
        path = self.upload_dir if self.upload_dir.is_absolute() else (REPO_ROOT / self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
