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

- No HTTP routes for content yet — `app/routers/public.py` and
  `admin.py` don't call into WorkService/ChapterService yet. That's
  Phase 3 (public reads) and Phase 4 (admin writes, behind auth).
- No auth — `app/routers/admin.py` is an empty router on purpose; a
  route is never added there without a login check already in front of it.
- No finished visual design — `static/css/style.css` is a readable,
  undecorated baseline. The real typography/palette/layout identity is
  a Phase 3 decision made against real content, not guessed at now.
