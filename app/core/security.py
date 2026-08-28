"""
Security primitives for the admin CMS.

SHRINE has exactly one admin account (the site's author), configured
entirely through environment variables — there's no user table, no
registration flow, no roles. Auth is a signed session cookie
(Starlette's SessionMiddleware, installed in app/main.py) carrying a
single `is_admin` flag. This is deliberately the simplest thing that's
still genuinely secure for a single-operator site; a multi-user system
would need a real user table and is a different, bigger feature.
"""

import secrets
import time

import bcrypt
from fastapi import HTTPException, Request, status

from app.core.config import get_settings

settings = get_settings()

# ------------------------------------------------------------ passwords


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # A malformed hash (e.g. a misconfigured ADMIN_PASSWORD_HASH env
        # var) should fail closed, not crash the request with a 500.
        return False


# ----------------------------------------------------------------- csrf


def get_csrf_token(request: Request) -> str:
    """
    Get (or lazily create) this session's CSRF token. Reused for the
    whole session rather than regenerated per-request/per-form — the
    token only needs to be unguessable and tied to the session, which a
    signed session cookie already guarantees.
    """
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, submitted_token: str) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not secrets.compare_digest(expected, submitted_token or ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your session expired or this form was submitted from a stale page. Go back and try again.",
        )


# ------------------------------------------------------------------ auth


def require_admin(request: Request) -> None:
    """
    FastAPI dependency — attach to every admin route except login/logout.

    Raising a 303 with a Location header (rather than a plain 401/403)
    means an unauthenticated visit to any admin page just lands on the
    login form, which is the behavior an admin actually wants when
    their session has expired.
    """
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})


# --------------------------------------------------------------- flashes


def flash(request: Request, message: str, category: str = "success") -> None:
    """Queue a one-time message, shown on the next page the session renders."""
    flashes = request.session.get("flashes", [])
    flashes.append({"message": message, "category": category})
    request.session["flashes"] = flashes


# ---------------------------------------------------- login rate limiting

# In-memory and per-process on purpose: this is a Stage-1, single-instance
# deployment (see ARCHITECTURE.md's scaling table). If SHRINE is ever
# horizontally scaled behind a load balancer, this stops being effective
# across instances — that's a real limitation worth knowing about, not a
# silent one, and the fix at that point is a shared store (e.g. Redis),
# introduced only when that scaling stage actually arrives.
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 15 * 60


class _LoginRateLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}

    def _recent_failures(self, key: str) -> list[float]:
        cutoff = time.monotonic() - _LOCKOUT_SECONDS
        attempts = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = attempts
        return attempts

    def is_locked_out(self, key: str) -> bool:
        return len(self._recent_failures(key)) >= _MAX_ATTEMPTS

    def record_failure(self, key: str) -> None:
        self._recent_failures(key).append(time.monotonic())

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)


login_rate_limiter = _LoginRateLimiter()
