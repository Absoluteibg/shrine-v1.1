"""
Admin CMS routes (Phase 4).

Intentionally empty for now. Every route added here must sit behind an
authentication/authorization dependency — there should never be a commit
where an admin route exists without a login check already in front of
it, so the router stays empty until that dependency is built.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])
