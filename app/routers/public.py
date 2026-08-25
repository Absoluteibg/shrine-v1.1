"""
Public-facing routes: the read-only literary site any visitor can reach.

No authentication. This router (and the services it calls) must only
ever expose PUBLISHED content — draft and archived Work/Chapter rows are
never returned here. That rule is enforced at the repository layer once
those models exist (Phase 2), so a route can't accidentally bypass it by
forgetting a status filter.
"""

from fastapi import APIRouter, Request

from app.core.templating import templates

router = APIRouter(tags=["public"])


@router.get("/")
def home(request: Request):
    """
    Foundation placeholder.

    Phase 3 replaces this with the real homepage (recent/featured
    published works via WorkService). It exists now only to prove the
    router -> Jinja2 -> static-asset pipeline works end to end.
    """
    return templates.TemplateResponse(request, "home.html", {})
