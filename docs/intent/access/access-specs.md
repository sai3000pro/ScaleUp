# Access — EARS Specs

Prefix: `ACCESS`. Facets: `AUTH` (credentials and tokens), `SESSION` (refresh),
`OAUTH` (federated identity), `RECOVER` (password reset), `SHARE` (share links),
`OWN` (ownership).

Status: `[x]` observed working in current code · `[ ]` specified but broken or partial ·
`[D]` deliberate non-want.

---

## Credentials and tokens

- [x] **ACCESS-AUTH-001**: The system shall store a password only as a salted hash.
- [x] **ACCESS-AUTH-002**: The system shall issue a signed, expiring access token on successful sign-in.
- [x] **ACCESS-AUTH-003**: The system shall require a valid access token on every authenticated route.
- [x] **ACCESS-AUTH-004**: The system shall reject a token whose signature, expiry or subject does not verify.
- [x] **ACCESS-AUTH-005**: The system shall answer a failed sign-in without revealing whether the account exists.
- [D] **ACCESS-AUTH-006**: No token issued by the system shall be stored in a form that can be replayed.
- [x] **ACCESS-AUTH-007**: Where development sign-in is disabled, its route shall not be registered at all.
- [x] **ACCESS-AUTH-008**: The system shall refuse to start with a placeholder signing secret when marked as deployed.

## Sessions

- [x] **ACCESS-SESSION-001**: The system shall issue a long-lived refresh session stored as a hash.
- [x] **ACCESS-SESSION-002**: The system shall deliver the refresh credential as a cookie rather than in a response body.
- [x] **ACCESS-SESSION-003**: The system shall rotate a refresh session on use.
- [x] **ACCESS-SESSION-004**: The system shall revoke a refresh session on sign-out, and a revoked session shall not be usable again.
- [x] **ACCESS-SESSION-005**: The system shall reject an expired refresh session.

## Federated identity

- [x] **ACCESS-OAUTH-001**: Where federated credentials are configured, the system shall offer federated sign-in; where they are not, it shall not.
- [x] **ACCESS-OAUTH-002**: While federated sign-in is unavailable, email and password sign-in shall remain fully available.
- [x] **ACCESS-OAUTH-003**: The system shall protect the federated exchange with a single-use, expiring state value stored as a hash.
- [x] **ACCESS-OAUTH-004**: The system shall exchange the provider's response for a short-lived, single-use code stored as a hash.
- [x] **ACCESS-OAUTH-005**: The system shall link a federated identity to an existing account with the same verified address rather than creating a duplicate.

## Recovery

- [x] **ACCESS-RECOVER-001**: The system shall issue a single-use, expiring reset token stored as a hash.
- [x] **ACCESS-RECOVER-002**: The system shall answer a reset request identically whether or not the address is registered.
- [x] **ACCESS-RECOVER-003**: When a reset token is consumed, the system shall mark it used and reject any further use.
- [x] **ACCESS-RECOVER-004**: Where no mail provider is configured, the system shall record the reset link rather than failing the request.
- [x] **ACCESS-RECOVER-005**: When a password is reset, the system shall revoke existing refresh sessions.

## Sharing

- [x] **ACCESS-SHARE-001**: The system shall issue a share token stored as a hash.
- [x] **ACCESS-SHARE-002**: The system shall serve a share preview without requiring the viewer to be signed in.
- [x] **ACCESS-SHARE-003**: The system shall permit the owner to revoke a share, after which the token shall not resolve.
- [x] **ACCESS-SHARE-004**: Copying a shared course shall require the viewer to be signed in.
- [x] **ACCESS-SHARE-005**: The system shall report a share's status to its owner.

## Ownership

- [x] **ACCESS-OWN-001**: When a caller requests a resource they do not own, the system shall answer as though it does not exist rather than as forbidden.
- [x] **ACCESS-OWN-002**: The system shall scope every course, document, attempt and recording query to its owner.
- [x] **ACCESS-OWN-003**: The system shall permit an owner to delete their own recordings permanently.
- [ ] **ACCESS-OWN-004**: A route shall obtain the authenticated principal from its dependency rather than importing a persistence entity directly.
