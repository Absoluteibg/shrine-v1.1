# Architecture

Guiding principle: **prototype for speed, architect for scale.** The
first version stays simple. The boundaries between layers are what stay
disciplined, because boundaries are what make future scaling cheap.

## Request flow

```
Browser
  → FastAPI Router      (app/routers)   HTTP in/out only, no queries
  → Service             (app/services)  business rules, publishing logic
  → Repository          (app/repositories) the only layer that queries the DB
  → SQLAlchemy / SQLite (app/db)
```

A router never imports SQLAlchemy or touches a `Session` for a query
directly. A service never imports `sqlite3` or writes raw SQL. This is
enforced by convention, not tooling — worth a second look in code
review, since it's the thing that makes the SQLite → PostgreSQL move
(and any later repository swap) a contained change instead of a
search-and-replace.

## Why SQLAlchemy + Alembic from the start

The app talks to `Session` objects and ORM models, never to
SQLite-specific SQL. `DATABASE_URL` is the only thing that knows which
database engine is in use (see `app/core/config.py` and
`app/db/database.py`). Moving to PostgreSQL later is:

1. `pip install psycopg2-binary`
2. Change `DATABASE_URL` in `.env`
3. `alembic upgrade head` against the new database

No application code changes. This is also why migrations exist from
commit one, rather than being retrofitted later — "the schema is
whatever SQLite currently has" is not a state that survives a database
migration.

## Why repository/service separation, even for a personal site

For a single-author site this feels like extra ceremony today. The
payoff shows up the first time a rule needs to apply everywhere at once
— e.g. "draft content is never visible on public routes." That rule
lives once, in the repository layer (a `list_published()` method that
public services call, versus a separate method admin services use), so
it can't be accidentally bypassed by a router that forgot a filter.

## Configuration

All environment-dependent values flow through `app/core/config.py`
(`pydantic-settings`, reading `.env`). Nothing else calls `os.environ`
directly. This is what makes "what changes between my laptop and a real
server" a one-file question.

## Content storage

The database stores paths/references to media (`static/images/...`),
never binary image data. That keeps the door open to swapping local
disk for object storage + a CDN later by changing where a path resolves
to, not the content model itself.

## Publishing states (Phase 2)

Work and Chapter share one publishing vocabulary — DRAFT, PUBLISHED,
ARCHIVED — and one set of transition rules, defined once in
`app/services/publishing.py` rather than duplicated per entity:

- DRAFT → PUBLISHED, PUBLISHED → DRAFT/ARCHIVED, ARCHIVED → DRAFT/PUBLISHED.
- DRAFT → ARCHIVED is **not** allowed: ARCHIVED means "this was live,
  then retired." A draft that was never published has nothing to
  retire — delete it instead.
- `published_at` is set the first time something becomes PUBLISHED and
  preserved through every later transition, so unpublishing and
  republishing doesn't lose the original publish date.

Public visibility is a query-layer rule, not a router-layer one: a
chapter is only reachable through `get_published_by_work_and_slug` when
**both** it and its parent Work are PUBLISHED. An archived/draft work
hides all of its chapters regardless of their own status.

## Tag identity is the slug, not the name

`TagRepository.get_or_create` looks up existing tags by slug, not by
raw name string. "Nature" and "nature" both slugify to `nature` and
resolve to the same row — first-seen casing wins as the display label.
Deduping on the raw string instead would let the same Tag object end up
twice in a Work's tag list, which fails at flush time (SQLAlchemy tries
to insert the same `(work_id, tag_id)` row twice).

## A SQLAlchemy enum gotcha we hit (and fixed)

By default, SQLAlchemy's `Enum` type persists a Python enum's **name**
(`"DRAFT"`), not its `.value` (`"draft"`) — easy to miss, since nothing
errors until something relies on the mismatch. Combined with
`create_constraint=True` (which adds a real `CHECK` constraint from the
same values), the default behavior would have produced a `CHECK
(status IN ('DRAFT','PUBLISHED','ARCHIVED'))` that silently disagreed
with `server_default='draft'` — fine through the ORM, but a landmine
for any future raw-SQL insert or backfill script. Both `status_enum_type()`
(`app/models/enums.py`) and the `Work.type` column pass
`values_callable` explicitly so the stored value, the `CHECK`
constraint, and the API's JSON representation all agree on lowercase
values.

## Visual design (Phase 3)

The concept: SHRINE is a dark, hushed archive for browsing. Opening a
chapter shifts the page itself to a lit parchment surface — like
holding a manuscript up to candlelight. That tonal shift is the one
deliberate signature move (see `static/css/style.css`); everything
around it — layout, motion, chrome — stays quiet on purpose. It's
scoped via `body.reading main` (set by `{% block body_class %}` in
`templates/chapter.html`) rather than a per-page stylesheet, so the
header/footer stay visually consistent everywhere and only the reading
surface itself changes.

No web fonts are loaded — the type stack (`Iowan Old Style` → `Palatino`
→ `Georgia` → serif) uses whatever the visitor's OS already has, so
there's no added network request or render-blocking font fetch.

## A test isolation bug we caught and fixed

The original `test_engine` fixture was session-scoped: one SQLite file
shared by the entire test run. That's invisible as long as tests only
assert on things scoped to the IDs they created themselves — which is
exactly what Phase 2's service-level tests did. It broke the moment
Phase 3 added tests that assert on *page content broadly* (e.g. "the
home page's empty state shows when nothing is published") — data from
unrelated tests was still sitting in the shared database. Fixed by
making `test_engine` function-scoped: a fresh SQLite file per test,
every time. Worth knowing if a future test starts failing for a reason
that doesn't match what the test itself does — check whether it's
seeing another test's data before assuming the application is wrong.

## Admin auth (Phase 4)

SHRINE has exactly one admin — the site's author — configured entirely
through environment variables (`ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`).
There's no user table, no registration flow, no roles. That's a
deliberate scope decision, not a shortcut: a real multi-user system
(accounts, permissions, password resets) is a different, bigger
feature that this site has no current need for. If SHRINE ever needs
more than one editor, that's the point to add a `users` table and
migrate the single env-var account into it — not before.

Sessions are **signed cookies** (Starlette's `SessionMiddleware`,
keyed on `SECRET_KEY`), not a server-side session store. There's
nothing to look up on each request and nothing to clean up — the
tradeoff is that a session can't be remotely revoked before it expires
(`SESSION_MAX_AGE_SECONDS`, 7 days by default). For one admin account,
that's the right tradeoff; it stops being one long before a `users`
table would be needed anyway.

`require_admin` (`app/core/security.py`) is attached explicitly via
`dependencies=[Depends(require_admin)]` on every protected route,
rather than once at the router level — consistent with this codebase's
general preference for explicit over clever (see `app/routers/public.py`'s
eight explicit type routes instead of one dynamic one). The cost is
repetition; the benefit is that "is this route protected" is answered
by looking at the route itself, not by tracing router configuration.

CSRF tokens are generated once per session (`get_csrf_token`) and
checked with `secrets.compare_digest` on every POST. Because the
session cookie itself is already tamper-proof (signed with
`SECRET_KEY`), the CSRF token doesn't need its own signing — it only
needs to be unguessable and tied to the session, which storing it in
the session already guarantees.

The login rate limiter (`app/core/security.py`) is a plain in-memory
dict, intentionally. It's a Stage-1 (single-process) mitigation — see
the scaling table below. If SHRINE is ever horizontally scaled behind
a load balancer, each instance would track lockouts independently,
which weakens it. That's a known, documented limitation, not a silent
one; the fix at that point is a shared store, introduced only when
that scaling stage actually arrives.

## Security headers

`app/main.py` sets `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy`, and a `Content-Security-Policy` of `default-src
'self'` on every response. That CSP has no `'unsafe-inline'`
exception, which is why `static/js/admin.js` attaches its delete
confirmations via `addEventListener` instead of `onsubmit="..."`
attributes — inline event handlers would be silently blocked by the
policy above. If a future page genuinely needs inline script/style,
that's a deliberate, visible change to the CSP, not a workaround.

## Two bugs caught while building the admin CMS

**Naive pluralization.** An early version of the work-edit page built
its "existing URL" display as `/{{ work.type.value }}s/{{ work.slug }}`
— which renders "story" as "storys". Fixed by reusing
`public.py`'s actual `segment_for()` mapping instead of re-deriving
(and getting wrong) the same logic a second time. Worth remembering:
anywhere a URL segment is displayed, it should come from the one
function that owns that mapping, never be reconstructed inline.

**A flash-message test bug.** A test created a work, then asserted its
title was absent from a *different, filtered* listing page — and
failed, even though the filter itself worked correctly. The title was
present, but as part of the one-time "'X' created as a draft" flash
message, still queued because the test jumped straight to the listing
without rendering an intermediate page (flashes are popped by whichever
template renders next, not tied to a specific route). Fixed the test,
not the app. Worth knowing about flash-message systems generally: a
broad "is this text present" assertion is vulnerable to unrelated
one-time UI state, not just to real data.

## Phase 5: quality review findings

A deliberate audit pass, not new features — going through the project
brief's Phase 5 checklist (validation, error handling, logging,
security, backups, performance) against what Phases 1–4 actually built.
What follows is what was found and fixed.

**Validation.** Chapter `content` had no upper bound — a pathological
paste could create an arbitrarily large row. Capped at 500,000
characters (multiple novels' worth) in both `ChapterCreate` and
`ChapterUpdate`: bounds abuse without constraining any real use.

**Error handling.** `validate_production_config()` (`app/core/config.py`)
replaced three separate inline checks in `main.py`'s lifespan handler
with one function that reports every problem at once (SECRET_KEY,
ADMIN_PASSWORD_HASH, and a new check: DEBUG must be False in
production, since DEBUG=True leaks stack traces). Extracting it also
made it directly unit-testable without booting the app — see
`tests/test_config_validation.py`.

A global `@app.exception_handler(Exception)` now catches anything not
already handled — a real bug, a DB hiccup, anything unanticipated —
logs it server-side with full context, and renders `templates/500.html`
instead of a framework traceback. One subtlety worth knowing: FastAPI
only dispatches to a custom `Exception` handler when `app.debug=False`.
With `DEBUG=True` (the local dev default), Starlette's interactive
traceback page takes over instead — which is what you want while
developing. `validate_production_config` is what guarantees `DEBUG=True`
can never reach an actual production deployment, so this isn't a gap in
practice.

**Logging.** Admin actions were only logged on failure (bad login
attempts). Successful logins/logouts and every work/chapter
create/publish/unpublish/archive/delete are now logged at INFO (WARNING
for deletes, the one irreversible action) — a basic audit trail: who
did what, when. Per-request access logging was deliberately *not*
added at the app level — uvicorn's own access log already covers that,
and duplicating it would just be noise.

**Security review.** Systematically checked against the project brief's
list:
- Confirmed via `grep` that no raw SQL string construction exists
  anywhere in the codebase, and no template bypasses autoescaping
  (`|safe`, `Markup(`) anywhere — every DB query goes through
  SQLAlchemy's parameterized queries, every template interpolation is
  escaped by Jinja by default.
- Added explicit tests proving that escaping (titles, descriptions,
  chapter content, and admin form re-population, which echoes values
  into `value="..."` attributes — a classic injection vector if handled
  wrong) actually works, rather than just assuming Jinja's default
  behavior — see `tests/test_output_escaping.py`.
- Added a systematic test asserting **every** admin route requires
  authentication (`tests/test_admin_authorization.py`), not just the
  handful that had ad-hoc coverage from Phase 4. It combines an
  explicit, readable list of routes with an introspection check that
  fails if a future route is added without a matching test entry — so
  "someone added a route and forgot `Depends(require_admin)`" can't
  silently ship untested.
- File upload handling remains explicitly out of scope — `cover_image`
  is still a path/URL text field, not a file upload. Nothing to review
  because nothing exists yet.

**Performance review.** Two real issues, both fixed with tests proving
the fix:
- Sitemap generation ran one chapter query *per published work* — a
  textbook N+1. Fixed with `ChapterRepository.list_published_grouped_by_work`,
  one query for every work's chapters at once. A regression test
  (`tests/test_performance.py`) counts actual SQL statements executed
  via a SQLAlchemy event listener and asserts the count stays small
  regardless of catalog size — not just that the sitemap's *content*
  is still correct, which wouldn't have caught the N+1 in the first
  place.
- Every table-of-contents view (public work page, admin chapter list,
  prev/next reading navigation) was loading full chapter body text via
  `ChapterRepository.list_by_work`, just to render a list of titles —
  exactly the "loading entire novels when only metadata is required"
  case the brief warns about. Fixed with `defer(Chapter.content)` on
  that query; the one caller that legitimately needs body text (the
  actual reading page) uses a different, single-row method and is
  unaffected.
- `GZipMiddleware` added — free (ships with Starlette, a FastAPI
  dependency already; no new package) and meaningful for a site whose
  entire purpose is serving long-form, highly-compressible prose.
- Caching was deliberately *not* added. Nothing here is expensive
  enough to justify it yet, per the project's build → measure → fix
  philosophy; the N+1 fix already makes sitemap generation cheap at any
  realistic catalog size.

**Database backups.** `scripts/backup_db.py` uses SQLite's own online
backup API (via Python's `sqlite3` module) rather than a raw file copy
— safe to run while the app is live, since it copies page-by-page under
SQLite's own locking instead of risking a half-written page mid-copy.
Writing it surfaced a real parsing bug before it ever shipped: naively
using `urllib.parse.urlparse` on a SQLAlchemy SQLite URL silently
corrupts the relative-path case. SQLAlchemy's convention is that slash
count is meaningful —

```
sqlite:///relative/path.db    (3 slashes -> relative)
sqlite:////absolute/path.db   (4 slashes -> absolute)
```

— which `urlparse` has no way to know; it treats both as an absolute
path, turning `sqlite:///./shrine.db` into `/./shrine.db`, resolving to
`/shrine.db` at the filesystem root. The script parses this itself
based on the actual convention instead. Covered directly in
`tests/test_backup_script.py`, including the exact case that would have
been silently wrong.

## Phase 6: PostgreSQL migration (Stage 2)

The project brief's own architecture principle, cashed in: *"The
application must be designed so SQLite can later be replaced by
PostgreSQL with minimal changes."* This phase tested that claim for
real rather than trusting it — every decision below was made
specifically to make this migration boring, going back to Phase 1.

**What actually changed:** one dependency (`psycopg2-binary`) and one
value (`DATABASE_URL`). Nothing in `app/models`, `app/repositories`,
`app/services`, `app/routers`, or any template was touched.

**What made that possible, decided long before this phase:**
- `app/db/database.py`'s only SQLite-specific line
  (`check_same_thread`) is conditional on the URL scheme — meaningless
  and unused for Postgres.
- Every enum column (`Work.type`, `Work.status`, `Chapter.status`) uses
  `native_enum=False` — VARCHAR + CHECK, not a native SQLite or
  Postgres enum type — specifically because native Postgres enums are
  awkward to alter later (see the Phase 2 note on this). Verified now:
  `\d works` against the real Postgres schema shows exactly the
  `CHECK (status::text = ANY (ARRAY['draft', 'published',
  'archived']...))` constraint this was designed to produce.
- No raw SQL exists anywhere in the codebase (confirmed by grep in
  Phase 5) — every query goes through SQLAlchemy, which handles the
  dialect differences (`SERIAL` vs `AUTOINCREMENT`, `TIMESTAMP WITH
  TIME ZONE` vs SQLite's untyped storage, etc.) automatically.
- Alembic's migrations use portable operations (`String`, `Text`,
  `ForeignKey(ondelete="CASCADE")`, `UniqueConstraint`, `Index`) with
  no SQLite-specific `batch_alter_table` recipes — both existing
  migrations applied to a fresh PostgreSQL 16 database with no edits.

**How it was verified** (not just asserted): a real PostgreSQL 16
server, both existing Alembic migrations applied cleanly, the full
158-test suite run against it end-to-end (`TEST_DATABASE_URL`, see
below), a complete manual content lifecycle exercised through live
HTTP (login → create work → create chapter → publish → visible on the
public site → correct in the sitemap), the XSS-escaping tests re-run
against Postgres-backed rendering, and a real `pg_dump` backup
restored into a fresh database with `pg_restore` to confirm the data
round-trips correctly.

**Test infrastructure:** `tests/conftest.py`'s `test_engine` fixture
now branches on a `TEST_DATABASE_URL` environment variable. Unset
(default): the original fast, zero-dependency temp-SQLite-file-per-test
behavior, untouched. Set to a Postgres URL: the identical test suite
runs against that server instead, using `create_all`/`drop_all` per
test for equivalent isolation (a fresh schema per test, just via DDL
against a shared server rather than a fresh file). This is a
verification path, not a CI default — SQLite stays the fast path for
everyday iteration; Postgres is there to prove production parity on
demand.

**Backup script generalized, not replaced:** `scripts/backup_db.py`
now dispatches on `DATABASE_URL`'s scheme — SQLite's online backup API
as before, or `pg_dump -Fc` for Postgres, using the same `--keep`
pruning and the same `backups/` directory (different filename pattern
per type: `shrine-<ts>.db` vs `shrine-pg-<ts>.dump`, so pruning one
type never touches the other). One subtlety handled deliberately: the
Postgres password is passed to `pg_dump` via the `PGPASSWORD`
environment variable, never as a command-line argument — CLI args are
visible to other local users via `ps`, environment variables scoped to
one subprocess are not.

## Scaling path

| Stage | Trigger | Change | Status |
|---|---|---|---|
| 1 | — | FastAPI + SQLite + local media | done (Phase 1) |
| 2 | Real traffic needs it | PostgreSQL + object storage + CDN | **PostgreSQL done (Phase 6)** — object storage/CDN still pending real media uploads |
| 3 | Measured bottleneck | Load balancer + multiple app instances | not started |
| 4 | Measured bottleneck | Caching / background workers / search infra | not started |

Nothing in this table gets built preemptively — Stage 2's database
half only moved now because it was explicitly requested, not because
traffic demanded it. Each remaining row still requires a measured
reason, per the project's development philosophy: build, measure,
identify the actual bottleneck, fix that bottleneck.

## What's still deliberately missing

- No deployment docs or process yet — that's Phase 7: documenting
  deployment steps and rollback, then deploying the simplest reliable
  version, now with PostgreSQL as the target production database.
- No author bio content — `templates/about.html` ships with bracketed
  placeholder copy; it's meant to be edited directly, not generated.
- No image handling yet — `cover_image` exists on the Work model and
  the admin form accepts a path/URL, but nothing uploads or validates
  an actual file. Add when there's a real cover to show (this is also
  the other half of Stage 2 — object storage — still pending).
