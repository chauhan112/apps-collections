# Task: Consolidate file backends — single Django backend, files on D2, DB on D1

## Devices
- **D1 (mini-pc)** — app host, exposed via Cloudflare
- **D2 (pc)** — file storage host, reachable via DuckDNS
- **D3** — you (the agent); SSH access to D1 and D2; do all work over SSH

## Current state (D1)
| service | detail |
|---|---|
| Flask gateway | `~/timeline/global/apps-server`, gunicorn :8003, systemd `app-center`, proxies `/backend/*` → :8500 |
| Django backend | `~/timeline/global/backend`, gunicorn :8500, systemd `app-backend` |
| PostgreSQL 17 | `~/timeline/global/backend-db` (container `backend-postgres`, port 5433) |
| Backups | `~/timeline/global/backups` — nightly encrypted `pg_dump` (gpg, `.backup-key`) + git push |
| Unit mgmt | bashrc `sys-*` helpers (`sys-ls`, `sys-status <name>`, `sys-restart <name>`); no passwordless sudo |

**Problem:** two separate backend-repo file servers exist (G1 and G2 — same Django codebase deployed twice just to serve files). New apps needing uploads are forced onto the DuckDNS path. Goal: **one backend** on D1 — DB entries in its Postgres, uploaded files stored on D2's disk.

## Constraints
- Never read/print `.env` files (append/sed/count keys only, never display values).
- Never commit/push without explicit user approval; no secrets in repos.
- Same LAN between D1↔D2; D2 may reboot/be offline — file features must degrade gracefully (clear error), not crash the backend.
- Keep the backend codebase device-agnostic: all D2 specifics via env vars (same pattern as existing `DATABASE_*` in `config/settings.py`).

## Phase 0 — discover (report before changing anything)
1. Locate G1 and G2: repos, which device each runs on, ports, how they're exposed (DuckDNS domain? ports? systemd/pm2?), their `MEDIA_ROOT`/upload dirs and file counts/sizes.
2. Inventory how files are referenced in DBs/URLs of G1/G2 (absolute URLs? relative paths? which tables).
3. Confirm upload-size requirements (>100 MB ⇒ uploads must bypass Cloudflare; <100 MB ⇒ can flow through the D1 backend).

## Phase 1 — design decision (pick one, get user approval)
- **A. Shared storage:** export a dir on D2 (NFS) → mount on D1 → `MEDIA_ROOT` points at it. Simplest; uploads still route browser→Cloudflare→D1→D2. Requires uploads <100 MB.
- **B. Direct upload endpoint on D2:** small service on D2 (nginx WebDAV / MinIO / minimal Django) accepting browser uploads via DuckDNS; backend on D1 stores only the returned file URL. Required if uploads are large.

## Phase 2 — implement (on approval)
1. Backend (`config/settings.py`): env-driven `MEDIA_ROOT` / storage backend (+ `.env.sample` docs) following the existing `DATABASE_*` pattern.
2. Wire D2 storage (NFS export + fstab mount, or the upload service + systemd unit named `app-*`).
3. Migrate existing G1/G2 files into the new storage; update DB rows referencing old URLs/paths; keep a pre-migration backup (follow the encrypted-backup pattern — never push plaintext dumps).
4. Point new apps at the single backend; decommission G1 and G2 (stop services, remove from exposure, archive repos).

## Phase 3 — verify
- Upload/download round-trip through one backend with files landing on D2, DB rows on D1 Postgres.
- D2 offline ⇒ uploads fail cleanly, rest of backend unaffected; D2 back ⇒ recovers without restart.
- Existing apps still serve previously uploaded files.
