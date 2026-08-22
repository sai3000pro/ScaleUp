---
parent: high-level-design
prefix: ACCESS
---

# Access

## Context and Design Philosophy

Access owns who a request is, what they may reach, and how a course reaches someone who does
not own it. It covers registration and sign-in, federated identity, session refresh,
password recovery, and share links.

**No credential is stored in a form that can be replayed.** Every token this segment issues
is persisted as a hash — password reset tokens, federated-identity state, exchange codes,
refresh sessions, and share tokens. Five tables, no plaintext column among them, each
carrying a consumption or revocation timestamp so a token can be spent exactly once and
withdrawn deliberately.

**One primary mechanism, and deliberate exceptions.** A bearer token covers almost every
authenticated route. The exceptions exist because the transport demands them, and each is
documented where it lives: a refresh cookie for session renewal, a first-frame token for the
WebSocket handshake, a share token that *is* the credential for a public preview, a signed
digest for machine callers, and a development sign-in that only exists when explicitly
enabled.

**Absence beats refusal for development affordances.** When development sign-in is disabled
the route is not registered at all, rather than registered and refusing. A route that exists
and says no is a route someone can probe.

**Not found, not forbidden.** A resource the caller does not own answers as though it does
not exist. Distinguishing "forbidden" from "absent" tells an unauthorised caller that the
resource is real. This convention is applied across the ownership-checked surfaces with the
same justification recorded at each.

## Sessions

An access token is short-lived and bearer; a refresh session is long-lived, stored hashed,
and delivered as a cookie whose name is configurable — renaming it signs every existing
session out, which is a deliberate lever rather than an accident.

## Federated identity

Sign-in with a federated provider is enabled by configuring its credentials; there is no
separate switch. Where it is not configured, email and password sign-in remains fully
available, so the absence of a provider is never a locked door.

The exchange is protected by a hashed, expiring state value and a short-lived exchange code,
both single-use.

## Recovery

A password reset issues a hashed, expiring, single-use token. Where no mail provider is
configured the link is logged rather than sent — which is what makes account recovery
testable locally without a mail account.

## Sharing

A course share issues a hashed token that grants a read-only preview and a copy-to-account
action. Copying is idempotent per learner, so the same share followed twice yields one copy.
The preview itself is unauthenticated by design: the token is the credential.

## Current state versus intent

**One router imports a model directly.** A single route module imports an ORM entity rather
than receiving it from the authentication dependency — the only such case among sixteen
routers, against the layering rule that routers do not reach past services.

**Development sign-in provisions data.** The development sign-in path creates its account on
demand, which means the affordance is not purely an authentication shortcut. Its blast
radius is bounded by the flag that registers it, but the behaviour is broader than the name.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Token storage | Hash only, with consumption/revocation timestamps | Store the token | A stored token is a replayable credential; a hash is a check. |
| Primary auth | Bearer access token | Session cookie throughout | A bearer token suits an API consumed by a separate front end. |
| WebSocket auth | Token in the first frame | Token in the query string | Browsers cannot set headers on a WebSocket handshake, and query strings are written to access logs. |
| Share preview | Token is the credential; route unauthenticated | Require sign-in to preview | A share that requires an account is not a share. |
| Copy semantics | Idempotent per learner | Copy per click | Following a link twice must not produce two courses. |
| Ownership failures | Answer not-found | Answer forbidden | Forbidden confirms the resource exists to a caller who should not know. |
| Dev sign-in | Route absent unless enabled | Route present, refusing | A refusing route is still a probe target. |
| Federated identity | Configuration enables it; no separate flag | An explicit toggle | Two switches for one capability is one switch too many. |
| Missing mail provider | Log the recovery link | Fail the request | Recovery must be exercisable with no mail account. |
| Refresh cookie name | Configurable | Fixed | Renaming is a deliberate global sign-out lever. |

## Open Questions & Future Decisions

### Deferred

1. **The router that imports a model directly** should take it from the dependency, or the
   layering rule should record this as an accepted exception.
2. **Whether development sign-in should provision accounts** or only authenticate existing
   ones.
3. **Deployment-time requirements are enforced in two places** with overlapping but
   non-identical rule sets — a hard startup check and an advisory report. Which is
   authoritative is unresolved; see `operations`.

## References

- `docs/api_contract.md` — auth, session and share contracts
- `docs/intent/operations/operations-design.md` — deployment-time credential enforcement
