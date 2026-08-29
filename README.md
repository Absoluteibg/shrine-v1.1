# SHRINE

A personal literary website — novels, short stories, poems, and essays —
built as a modular monolith that can grow into a larger publishing
platform without a rewrite. See [`ARCHITECTURE.md`](./ARCHITECTURE.md)
for the design rationale.

**Status: Phase 5 — Quality.** Consolidated security/performance review
complete: fixed a real N+1 query, capped unbounded content input, added
a global error handler with an on-brand 500 page, audit logging for
every content-lifecycle action, a database backup script, and 152 tests
passing — including a systematic check that every admin route requires
authentication.

## Requirements

- Python 3.11+

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env           # defaults are fine for local dev

# 4. Apply database migrations
alembic upgrade head            # creates shrine.db
```

## Run

```bash
uvicorn app.main:app --reload
```

- Site: http://127.0.0.1:8000/
- Health check: http://127.0.0.1:8000/health

## Test

```bash
python -m pytest tests/ -v
```

## Content model

| Entity | Key fields | Notes |
|---|---|---|
| **Work** | `title`, `slug`, `type` (novel/story/poem/essay), `description`, `cover_image`, `status`, `published_at` | slug is stable after creation |
| **Chapter** | `work_id`, `title`, `slug`, `content`, `chapter_number`, `status`, `published_at` | slug + chapter_number unique per work, not globally |
| **Tag** | `name`, `slug` | many-to-many with Work via `work_tags` |

Both Work and Chapter use the same publishing states: `draft` →
`published` → `archived`, with rules enforced in
`app/services/publishing.py`. See `ARCHITECTURE.md` for the details.

## Admin CMS

Visit `/admin` and log in. **Dev default: username `admin`, password
`changeme123`.** Change this before deploying anywhere real:

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'your-real-password', bcrypt.gensalt()).decode())"
```

Put the output in `.env` as `ADMIN_PASSWORD_HASH` (and set `ADMIN_USERNAME`
if you want something other than `admin`). The app refuses to start
with the dev-only default when `ENV=production`.

| Route | Purpose |
|---|---|
| `/admin/login` | Sign in (rate-limited: 5 failed attempts locks out for 15 min, per IP) |
| `/admin` | Dashboard — status counts, recent works |
| `/admin/works` | All works, any status, filterable |
| `/admin/works/new`, `/admin/works/{id}/edit` | Create/edit a work; publish, archive, delete, and the chapter list live on the edit page |
| `/admin/works/{id}/chapters/new`, `/admin/chapters/{id}/edit` | Create/edit a chapter; publish, archive, delete live on the edit page |

Security notes:
- Sessions are signed cookies (`SECRET_KEY`), not a server-side store —
  no session table, no Redis.
- Every mutating form carries a CSRF token, checked against the session
  before anything happens.
- The login rate limiter is in-memory and per-process — see
  `app/core/security.py` and ARCHITECTURE.md for the scaling caveat.
- `templates/about.html` still has placeholder copy — replace it with
  your own bio.

## Public site

| Route | Renders |
|---|---|
| `/` | Home — recent published works |
| `/about` | Static author bio — **edit `templates/about.html`**, it ships with placeholder copy |
| `/novels`, `/stories`, `/poems`, `/essays` | Type listings, paginated 20/page |
| `/novels/{slug}` (etc.) | Work detail + table of contents |
| `/works/{slug}/chapters/{slug}` | Chapter reading page |
| `/sitemap.xml`, `/robots.txt` | SEO — regenerated from published content on every request |

Draft and archived content is never reachable here — enforced in the
service layer (Phase 2), not the router. See ARCHITECTURE.md for the
design concept behind the reading page.

## Database backups

```bash
# Back up now (safe to run while the app is live — uses SQLite's own
# online backup API, not a raw file copy):
python scripts/backup_db.py

# Back up and prune, keeping only the 10 most recent:
python scripts/backup_db.py --keep 10
```

Backups land in `backups/` (gitignored) as `shrine-<timestamp>.db`.
Schedule it however you'd schedule anything else on your host — a cron
entry is the usual choice:

```cron
0 3 * * * cd /path/to/shrine && /path/to/.venv/bin/python scripts/backup_db.py --keep 30
```

**To restore:** stop the app, then replace the live database with a
backup file:

```bash
cp backups/shrine-20260315-030000.db shrine.db
```

There's deliberately no `restore` script — restoring is rare and
destructive enough to warrant a deliberate, manual step rather than a
command someone might run out of habit.

This is a SQLite-specific strategy (Stage 1 — see ARCHITECTURE.md).
Moving to PostgreSQL later means switching to `pg_dump` or your host's
managed backup/snapshot tooling instead of this script.

## Database migrations

SHRINE uses Alembic. The connection string comes from `DATABASE_URL` in
`.env` — Alembic never has its own separate copy of it.

```bash
# After changing/adding a model in app/models/:
alembic revision --autogenerate -m "describe the change"
alembic upgrade head

# Roll back one revision:
alembic downgrade -1
```

## Project layout

```
app/
  main.py            FastAPI app, wiring, startup checks
  core/
    config.py         Environment-based settings (single source of truth)
    security.py        Password hashing, CSRF, admin auth, rate limiting
    templating.py      Shared Jinja2 environment
  db/
    database.py        SQLAlchemy engine/session, declarative Base
    migrations/         Alembic
  models/               ORM models (Phase 2)
  schemas/              Pydantic request/response contracts (Phase 2)
  repositories/         Persistence — the only layer that queries the DB
  services/              Business rules
  routers/
    public.py            Public site (no auth)
    admin.py              CMS (Phase 4, auth-gated)
    api.py                 Versioned JSON API (/api/v1)
templates/               Jinja2 templates
static/                   CSS / JS / images
scripts/
  backup_db.py            Database backup (Phase 5)
tests/
```

## Development phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: config, DB, migrations, routing skeleton | ✅ done |
| 2 | Content system: Work / Chapter / Tag, repositories, services | ✅ done |
| 3 | Public website | ✅ done |
| 4 | Admin CMS + auth | ✅ done |
| 5 | Quality: validation, error handling, logging, security, backups, performance | ✅ done |
| 6 | Deployment | next |
| 7 | Real-world scaling (only as measured need appears) | planned |
