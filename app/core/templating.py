"""
Shared Jinja2Templates instance.

Every router imports `templates` from here instead of constructing its
own Jinja2Templates, so:
  - there is one template environment (custom filters/globals registered
    once, in one place, as the app grows), and
  - values every page needs (site name, current year) are injected
    automatically via `context_processors`, instead of every route
    remembering to pass them.
"""

from datetime import datetime, timezone

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.core.config import get_settings

settings = get_settings()


def _global_context(request: Request) -> dict:
    return {
        "app_name": settings.APP_NAME,
        "current_year": datetime.now(timezone.utc).year,
    }


templates = Jinja2Templates(
    directory=str(settings.TEMPLATES_DIR),
    context_processors=[_global_context],
)
