"""
SHRINE — application entrypoint.

Wires together configuration, static files, templates, and the three
router modules that define the app's boundaries:

    app/routers/public.py  -> public, read-only pages (no auth)
    app/routers/admin.py   -> authenticated CMS pages (Phase 4)
    app/routers/api.py     -> versioned JSON API (/api/v1/...)

Routers stay thin: request in, call a service, response out. Query
logic belongs in repositories (app/repositories); business rules belong
in services (app/services). See ARCHITECTURE.md for the full picture.

Run locally with:
    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings, validate_production_config
from app.core.templating import templates
from app.routers import admin, api, public
from app.services.exceptions import NotFoundError

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("shrine")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail loudly on startup rather than silently running an insecure
    # production deployment — wrong config here should never reach
    # "the server is up and serving traffic". See
    # app/core/config.py:validate_production_config for what's checked.
    validate_production_config(settings)

    logger.info(
        "%s starting up | env=%s debug=%s db=%s",
        settings.APP_NAME,
        settings.ENV,
        settings.DEBUG,
        settings.DATABASE_URL,
    )
    yield
    logger.info("%s shutting down", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Compresses text responses (HTML/CSS/JS) — meaningful for a
# long-form-prose site, and free: GZipMiddleware ships with Starlette
# (a FastAPI dependency already), so this adds no new package. A CDN
# would take over this job at Stage 2; not needed before then.
app.add_middleware(GZipMiddleware, minimum_size=500)

# Signed-cookie sessions for admin login. Only ever set for requests
# that actually touch session data (Starlette skips the Set-Cookie
# header when the session dict is empty) — anonymous visits to the
# public site never receive a cookie.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie=settings.SESSION_COOKIE_NAME,
    max_age=settings.SESSION_MAX_AGE_SECONDS,
    same_site="lax",
    https_only=settings.is_production,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # No inline <script>/<style> or onclick-style attributes exist
    # anywhere in the templates, so this stays strict rather than
    # carrying a standing 'unsafe-inline' exception. static/js/admin.js
    # attaches its confirm() handlers via addEventListener for exactly
    # this reason.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    return response


app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")

app.include_router(public.router)
app.include_router(admin.router)
app.include_router(api.router)


@app.get("/health", tags=["infra"])
def health_check() -> dict:
    """Liveness check for deployment/uptime tooling. Deliberately has no DB dependency."""
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENV}


# ---------------------------------------------------------- error handling

# This is the payoff for services raising plain NotFoundError instead of
# an HTTP-flavored exception (see app/services/exceptions.py): the
# translation to "404, rendered as our own page" happens once, here, no
# matter which public route triggered it.
@app.exception_handler(NotFoundError)
async def not_found_error_handler(request: Request, exc: NotFoundError):
    return templates.TemplateResponse(request, "404.html", {}, status_code=404)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # A genuinely unmatched URL also gets the on-brand 404 page — but
    # only for the public site. /api and /admin (Phase 4) keep plain
    # JSON error responses, since their clients are code, not a reader's
    # browser.
    if exc.status_code == 404 and not request.url.path.startswith(("/api", "/admin", "/static")):
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    return await default_http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    The last line of defense: any exception not already handled above
    (a real bug, a DB hiccup, anything unanticipated) lands here instead
    of leaking a framework traceback to a visitor. Logged with full
    context server-side — the person running SHRINE can see exactly
    what broke; a visitor just sees a plain, on-brand error page.

    Note: FastAPI only routes to this handler when `app.debug=False`
    (i.e. ENV=production-like settings). With DEBUG=True (the local dev
    default), Starlette's interactive traceback page takes over instead
    — which is what you want while developing. See
    validate_production_config for why DEBUG=True can never reach a
    real production deployment in the first place.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    if request.url.path.startswith("/api"):
        return await default_http_exception_handler(
            request, StarletteHTTPException(status_code=500, detail="Internal server error")
        )
    return templates.TemplateResponse(request, "500.html", {}, status_code=500)
