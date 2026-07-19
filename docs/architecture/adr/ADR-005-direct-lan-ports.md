# ADR-005: Direct LAN Ports for the Web Application

- **Status:** Accepted
- **Date:** 2026-07-20

## Context

The homelab deployment does not require Caddy for this application. The backend and frontend can be exposed as separate LAN-only services, avoiding an additional reverse-proxy dependency for the application path.

## Decision

- Backend FastAPI listens as non-root user `sportapp` on `0.0.0.0:8100`.
- Frontend production static files are served as non-root user `sportapp` on `0.0.0.0:8101`.
- Caddy remains installed but is stopped and disabled for this application.
- nftables allows ports 8100 and 8101 only from `10.10.10.0/24`; SSH remains allowed.
- The frontend uses `http://10.10.10.83:8100` as its production API origin.
- FastAPI allows credentialed CORS only from `http://10.10.10.83:8101` and `http://localhost:8101`.

## Cookie Security Trade-off

The application uses an HTTP-only session cookie. Because the direct LAN deployment uses plain HTTP rather than HTTPS, `Secure` must be disabled or browsers will not send the cookie. The cookie remains `HttpOnly`, uses `SameSite=Lax`, and CORS credentials are restricted to the two approved origins.

This is an explicit trusted-LAN trade-off: session cookies can be observed by an attacker able to monitor the LAN. HTTPS should be restored before exposing the application beyond the trusted homelab network.

## Consequences

- Deployment is simpler and has two explicit service endpoints.
- Caddy is not part of the application request path.
- The browser has cross-origin requests between ports 8101 and 8100.
- The backend must maintain a narrow CORS allowlist.
- Port-level firewall rules are mandatory and persist in `/etc/nftables.conf`.
- Future HTTPS adoption requires setting `SECURE_COOKIES=true` and updating the frontend API origin.

## Rollback

Re-enable the previous Caddy service/configuration and point the backend back to `127.0.0.1:8100`, or redirect the `current` symlink to the previous release. Restore the previous nftables configuration if the direct ports are removed.
