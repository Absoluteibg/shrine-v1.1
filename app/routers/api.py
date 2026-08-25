"""
Versioned JSON API, mounted at /api/v1.

Endpoints are added here only when they serve an actual client (the
admin UI's JS, or a future external consumer) — not speculatively.
Request/response contracts live in app/schemas, kept separate from the
ORM models in app/models so the DB shape can change without breaking
the public API contract.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["api"])
