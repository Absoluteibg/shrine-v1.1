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

## Scaling path (not built yet — for context)

| Stage | Trigger | Change |
|---|---|---|
| 1 (now) | — | FastAPI + SQLite + local media |
| 2 | Real traffic needs it | PostgreSQL + object storage + CDN |
| 3 | Measured bottleneck | Load balancer + multiple app instances |
| 4 | Measured bottleneck | Caching / background workers / search infra |

Nothing in this table gets built preemptively. Each row requires a
measured reason, per the project's development philosophy: build,
measure, identify the actual bottleneck, fix that bottleneck.

## What's still deliberately missing

- No comprehensive input-sanitization/security review pass yet — the
  individual pieces (CSRF, password hashing, security headers, output
  escaping via Jinja autoescape) are in place, but a dedicated Phase 5
  pass is still the right place to review them as a whole rather than
  trusting they compose correctly by construction.
- No author bio content — `templates/about.html` ships with bracketed
  placeholder copy; it's meant to be edited directly, not generated.
- No image handling yet — `cover_image` exists on the Work model and
  the admin form accepts a path/URL, but nothing uploads or validates
  an actual file. Add when there's a real cover to show.
- No deployment docs yet — that's Phase 6.
