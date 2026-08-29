# SHRINE

A personal literary website — novels, short stories, poems, and essays —
built as a modular monolith that can grow into a larger publishing
platform without a rewrite. See [`ARCHITECTURE.md`](./ARCHITECTURE.md)
for the design rationale.

**Status: Phase 6 — Scaling: PostgreSQL migration.** Production
database moved from SQLite to PostgreSQL, verified for real — the full
158-test suite passes against a live PostgreSQL server with zero
application code changes, only `DATABASE_URL`. See "Database" below.

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

Runs against a throwaway SQLite file per test by default — fast, zero
external dependencies. To run the exact same suite against PostgreSQL
instead (useful after touching anything DB-related, or just to confirm
the app still behaves identically on the production database):

```bash
export TEST_DATABASE_URL=postgresql+psycopg2://shrine:your-password@localhost:5432/shrine_test
python -m pytest tests/ -v
```

Use a **separate** database from your dev/production one — each test
creates and drops the full schema.

## Database

SQLite for local development, PostgreSQL for production — same code,
same migrations, same test suite either way. Only `DATABASE_URL`
changes; see `.env.example`. This isn't a theoretical claim: Phase 6
ran the entire 158-test suite, a full admin-to-public content
lifecycle, and every existing SQLite backup/migration workflow against
a live PostgreSQL server with zero application code changes.

**Moving an existing SQLite site to PostgreSQL:**

```bash
# 1. Create the database and a role for the app
sudo -u postgres psql -c "CREATE USER shrine WITH PASSWORD 'your-password';"
sudo -u postgres psql -c "CREATE DATABASE shrine OWNER shrine;"

# 2. Point DATABASE_URL at it in .env, then create the schema
alembic upgrade head

# 3. Migrate existing data (skip this on a fresh install)
#    pgloader handles the SQLite -> PostgreSQL type/data conversion in
#    one pass; it's not a Python dependency, install it separately.
pgloader shrine.db postgresql://shrine:your-password@localhost/shrine

# 4. Restart the app with the new DATABASE_URL
```

Everything else — repositories, services, routers, templates, tests,
Alembic migrations — is unchanged. This works because the schema was
deliberately kept portable from Phase 2 onward: enum columns use
`VARCHAR` + `CHECK` instead of a native SQLite/Postgres-specific enum
type (see ARCHITECTURE.md), and no raw SQL exists anywhere in the
codebase.

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

`scripts/backup_db.py` reads `DATABASE_URL` and backs up whichever
database is actually configured — same command either way:

```bash
python scripts/backup_db.py              # SQLite: shrine.db -> backups/shrine-<timestamp>.db
python scripts/backup_db.py --keep 10    # ...and prune, keeping the 10 most recent
```

- **SQLite**: uses SQLite's own online backup API — safe to run while
  the app is live, unlike a raw file copy.
- **PostgreSQL**: uses `pg_dump -Fc` (compressed, custom format).
  Requires the PostgreSQL client tools (`pg_dump` on `PATH` —
  `apt install postgresql-client` / `brew install postgresql`); these
  aren't a Python dependency, so they're not in `requirements.txt`.

Backups land in `backups/` (gitignored) — `shrine-<timestamp>.db` for
SQLite, `shrine-pg-<timestamp>.dump` for PostgreSQL. Schedule it
however you'd schedule anything else on your host:

```cron
0 3 * * * cd /path/to/shrine && /path/to/.venv/bin/python scripts/backup_db.py --keep 30
```

**To restore:**

```bash
# SQLite — stop the app first, then:
cp backups/shrine-20260315-030000.db shrine.db

# PostgreSQL:
pg_restore -h localhost -U shrine -d shrine --clean --if-exists backups/shrine-pg-20260315-030000.dump
```

There's deliberately no `restore` script — restoring is rare and
destructive enough to warrant a deliberate, manual step rather than a
command someone might run out of habit.

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
  backup_db.py            Database backup — SQLite or Postgres (Phase 5/6)
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
| 6 | Scaling: PostgreSQL migration (Stage 2) | ✅ done |
| 7 | Deployment | next |
