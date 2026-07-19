# ADR-002 — Session-Based Six-Digit PIN Authentication

**Date:** 2026-07-19 | **Status:** Accepted | **Scope:** Sport Prediction Web App

## Context

The first application release needs a lightweight login gate for a trusted homelab dashboard. There is no requirement for a full user-management system. The authentication secret is a six-digit PIN, which has low entropy and must be handled as a password-equivalent secret.

## Problem

A stateless or weakly protected PIN endpoint would be vulnerable to brute-force attempts, cookie/session fixation, and accidental credential disclosure. JWT would add complexity without improving this single-dashboard use case.

## Decision

Use server-side, session-based authentication with an Argon2id-hashed PIN.

Authentication behavior:

- Store only an Argon2id hash, never plaintext or reversible encryption.
- Verify through a vetted password-hashing library.
- Return the same generic failure response for invalid PINs and unknown authentication state.
- Rate-limit by client/network identity and logical application session/device.
- Persist failed-attempt counters server-side so clearing cookies does not reset protection.
- Apply progressive delay and temporary lockout after repeated failures.
- Rotate the session identifier after successful authentication.
- Store an opaque cryptographically random session token server-side.
- Send the token in a `Secure`, `HttpOnly`, `SameSite=Lax` cookie; use `Strict` if the intended flow permits it.
- Enforce idle timeout and absolute session lifetime.
- Require CSRF protection for state-changing cookie-authenticated requests.
- Do not log PINs, session tokens, or sensitive request bodies.

The PIN input is mobile-friendly: numeric input mode, paste support, one accessible underlying value, optional visual grouping, no forced auto-submit, and generic clear errors.

## Alternatives Considered

### A. JWT/stateless tokens

Rejected for the first release. Revocation, lockout, and session rotation are more complicated, while the app has no multi-service stateless-auth requirement.

### B. Plaintext or encrypted PIN storage

Rejected. A PIN must be hashed using a password-hashing function; encryption would make compromise of the key equivalent to plaintext disclosure.

### C. Client-only PIN check

Rejected. It exposes the secret and provides no brute-force protection.

### D. Full user/account system

Deferred. It adds scope not required for the initial single-dashboard homelab release.

## Consequences

### Positive

- Simple revocation and logout semantics.
- Server-side lockout and rate-limit state.
- No token claims or refresh-token lifecycle.
- Compatible with a single backend and browser dashboard.

### Negative

- Requires database-backed session state.
- Horizontal scaling would require shared session storage.
- A six-digit PIN remains weak even with good hashing; network exposure must be restricted.

## Security Boundaries

The service must remain on the trusted homelab/VPN network. Do not expose a six-digit PIN login to the public internet without stronger authentication and TLS. The PIN hash and session secrets must be loaded from server-side protected configuration, never committed or shipped to the frontend.

## Rollback Plan

Disable the new authentication middleware and stop the new backend service. Existing legacy prediction automation is unaffected because the web app is a separate consumer.

## Review Trigger

Revisit if the app becomes internet-facing, gains multiple users, or requires administrative actions beyond read-only dashboard access.
