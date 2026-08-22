# Arrow: access

Who a request is, what they may reach, and how a course reaches someone who does not own it.

## Status

**AUDITED** — last audited 2026-08-22 (git SHA `dc77249`). The cleanest segment in the
system: 31 of 32 specs implemented, one minor layering deviation outstanding.

## References

### HLD
- `docs/high-level-design.md`

### LLD
- `docs/intent/access/access-design.md`

### EARS
- `docs/intent/access/access-specs.md` (32 specs)

### Tests
- `backend/tests/unit/test_auth_security.py`
- `backend/tests/integration/test_auth_flow.py`, `test_dev_login_provisions.py`, `test_course_sharing.py`

### Code
- `backend/app/services/auth_service.py`, `email_service.py`
- `backend/app/api/routers/auth.py`, `dev.py`, `shares.py`
- `backend/app/api/deps.py`, `backend/app/core/`
- `backend/app/models/auth.py`, `share.py`
- `frontend/app/login/`, `forgot-password/`, `reset-password/`, `auth/callback/`, `share/[token]/`
- `frontend/components/AuthGate.tsx`, `frontend/stores/useAuthStore.ts`

## Architecture

**Purpose:** Issue and verify credentials without ever storing a replayable one, and make a
resource the caller does not own indistinguishable from one that does not exist.

**Key Components:**
1. Bearer access tokens for the authenticated surface, with documented per-transport exceptions.
2. Five hash-only token tables — reset, federated state, exchange code, refresh session, share — each with a consumption or revocation timestamp.
3. Federated identity, enabled by configuration alone.
4. Share tokens where the token is the credential.

## Spec Coverage

| Category | Spec IDs | Implemented | Deferred | Gaps |
|---|---|---|---|---|
| Credentials | `ACCESS-AUTH-001` – `008` | 7 | 1 | 0 |
| Sessions | `ACCESS-SESSION-001` – `005` | 5 | 0 | 0 |
| Federated identity | `ACCESS-OAUTH-001` – `005` | 5 | 0 | 0 |
| Recovery | `ACCESS-RECOVER-001` – `005` | 5 | 0 | 0 |
| Sharing | `ACCESS-SHARE-001` – `005` | 5 | 0 | 0 |
| Ownership | `ACCESS-OWN-001` – `004` | 3 | 0 | 1 |

**Summary:** 30 of 32 implemented; 1 deliberate non-want; 1 active gap.

## Key Findings

1. **No replayable credential is stored anywhere.** Five token tables, every one hash-only,
   every one carrying a consumption or revocation column. This is the most consistently
   applied security property in the codebase.

2. **Absence beats refusal for development affordances.** When development sign-in is
   disabled the route is not registered at all rather than registered and refusing — a route
   that exists and says no is still a probe target.

3. **Not-found rather than forbidden is a repository-wide convention**, applied across at
   least six ownership-checked surfaces with the same justification recorded at each. Copy
   without authentication is the one deliberate exception.

4. **One router imports a persistence entity directly.** `coach.py:22` imports `User` rather
   than taking it from the authentication dependency — the only such case among sixteen
   routers, against the stated layering rule (`ACCESS-OWN-004`).

5. **Development sign-in provisions its account on demand**, so the affordance is broader than
   authentication. Its blast radius is bounded by the flag that registers it, and startup
   refuses that flag when deployed.

6. **Three authentication mechanisms beyond the bearer token exist by transport necessity** —
   refresh cookie, WebSocket first-frame token, share token — each documented where it lives.

## Work Required

### Should Fix
1. Take the authenticated principal from the dependency rather than importing the entity
   (`ACCESS-OWN-004`).

### Consider
2. Decide whether development sign-in should provision accounts or only authenticate existing
   ones.
3. Reconcile the two places that enforce deployment-time credential requirements — see
   `operations`, `OPS-CONFIG-007`.
