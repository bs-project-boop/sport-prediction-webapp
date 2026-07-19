# ADR-004: Run Ingestion on Mac with Restricted PostgreSQL Access

- **Status:** Accepted
- **Date:** 2026-07-20

## Context

The Sport Prediction reports are generated on the Mac at `/Users/beem/.hermes-shared/reports/sports/v3`. LXC 108 cannot access that path: there is no shared mount, rsync job, NFS export, or Syncthing configuration. The PostgreSQL database runs in LXC 108 and originally listened only on localhost.

## Decision

Run the ingestion worker on the Mac and connect it to PostgreSQL on LXC 108. PostgreSQL listens on `127.0.0.1,10.10.10.83`, and `pg_hba.conf` permits only `sportapp` connecting to `sport_prediction` from the Mac address `10.10.10.65/32` using `scram-sha-256`.

The LXC ingestion systemd service and timer remain disabled. A Mac-side scheduler must be provisioned separately after the production database connection settings are supplied securely.

## Alternatives Considered

1. **Sync reports Mac → LXC, then run ingestion in LXC** — avoids database exposure but adds a report synchronization pipeline and freshness/permission failure modes.
2. **Run ingestion on Mac with restricted database access** — selected because the source data already lives on the Mac and the database exposure can be constrained to one host with SCRAM authentication.

## Consequences

- No report synchronization layer is required.
- PostgreSQL has one additional network listener and a narrowly scoped HBA rule.
- The Mac must remain online for ingestion jobs.
- The Mac-side worker needs a DSN using the LXC address and must not store credentials in source control.
- Port 5432 is firewall-allowlisted only for `10.10.10.65/32`; port 8080 is restricted to `10.10.10.0/24`.

## Security and Rollback

- Do not place the database password or production PIN in repository files or chat.
- Roll back by restoring the timestamped PostgreSQL configuration backups, returning `listen_addresses` to `localhost`, removing the Mac HBA rule, and reloading/restarting PostgreSQL.
- Roll back firewall changes by restoring `/etc/nftables.conf` from its pre-change backup and reloading nftables.
