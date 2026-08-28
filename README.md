# SHRINE

A personal literary website — novels, short stories, poems, and essays —
built as a modular monolith that can grow into a larger publishing
platform without a rewrite. See [`ARCHITECTURE.md`](./ARCHITECTURE.md)
for the design rationale.

**Status: Phase 4 — Admin CMS.** Session-based auth, CSRF protection,
a dashboard, and full Work/Chapter CRUD with publish/archive/delete are
live behind a single admin account. 107 tests passing.

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
tests/
```

## Development phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: config, DB, migrations, routing skeleton | ✅ done |
| 2 | Content system: Work / Chapter / Tag, repositories, services | ✅ done |
| 3 | Public website | ✅ done |
| 4 | Admin CMS + auth | ✅ done |
| 5 | Quality: validation, logging, security review, tests | next |
| 6 | Deployment | planned |
| 7 | Real-world scaling (only as measured need appears) | planned |
