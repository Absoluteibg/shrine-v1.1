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

## What Phase 1 deliberately does not include

- No domain models yet (`app/models` is an empty package) — added in
  Phase 2 once real content requirements exist.
- No auth — `app/routers/admin.py` is an empty router on purpose; a
  route is never added there without a login check already in front of it.
- No finished visual design — `static/css/style.css` is a readable,
  undecorated baseline. The real typography/palette/layout identity is
  a Phase 3 decision made against real content, not guessed at now.
