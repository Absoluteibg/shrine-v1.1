"""
Systematic authorization coverage.

Two complementary checks:
  1. An explicit list of every protected route, asserting each one
     redirects unauthenticated requests to /admin/login. Explicit and
     readable — matches this codebase's general preference (see
     app/routers/public.py, app/routers/admin.py) for spelling routes
     out rather than looping over dynamic registration data.
  2. An introspection check cross-referencing that list against the
     app's actual registered routes, so a future route added to
     admin.py without a matching entry here fails loudly instead of
     silently going untested.
"""

import re

import pytest

from app.main import app

# (method, path) for every admin route that must require authentication.
# Deliberately excludes /admin/login (GET+POST) and nothing else — those
# are the only two routes reachable while logged out.
PROTECTED_ADMIN_ROUTES: list[tuple[str, str]] = [
    ("GET", "/admin"),
    ("GET", "/admin/works"),
    ("GET", "/admin/works/new"),
    ("POST", "/admin/works/new"),
    ("GET", "/admin/works/{work_id}/edit"),
    ("POST", "/admin/works/{work_id}/edit"),
    ("POST", "/admin/works/{work_id}/publish"),
    ("POST", "/admin/works/{work_id}/unpublish"),
    ("POST", "/admin/works/{work_id}/archive"),
    ("POST", "/admin/works/{work_id}/delete"),
    ("GET", "/admin/works/{work_id}/chapters/new"),
    ("POST", "/admin/works/{work_id}/chapters/new"),
    ("GET", "/admin/chapters/{chapter_id}/edit"),
    ("POST", "/admin/chapters/{chapter_id}/edit"),
    ("POST", "/admin/chapters/{chapter_id}/publish"),
    ("POST", "/admin/chapters/{chapter_id}/unpublish"),
    ("POST", "/admin/chapters/{chapter_id}/archive"),
    ("POST", "/admin/chapters/{chapter_id}/delete"),
    ("POST", "/admin/logout"),
]


def _concrete_path(path: str) -> str:
    """Substitute any {param} placeholder with a dummy id — the auth check runs before the row lookup, so it doesn't need to be real."""
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.mark.parametrize("method,path", PROTECTED_ADMIN_ROUTES, ids=[f"{m} {p}" for m, p in PROTECTED_ADMIN_ROUTES])
def test_admin_route_requires_authentication(client, method, path):
    concrete = _concrete_path(path)
    if method == "GET":
        response = client.get(concrete, follow_redirects=False)
    else:
        response = client.post(concrete, data={"csrf_token": "irrelevant"}, follow_redirects=False)

    assert response.status_code == 303, f"{method} {path} returned {response.status_code}, expected a redirect"
    assert response.headers["location"] == "/admin/login", f"{method} {path} did not redirect to the login page"


def test_protected_route_list_matches_actual_registered_routes():
    """
    Drift guard: if a route is added to admin.py without a matching
    entry in PROTECTED_ADMIN_ROUTES above (or vice versa), this fails —
    catching "someone added a new admin route and forgot the auth
    dependency, AND forgot to test it" in one check.
    """
    actual: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or not path.startswith("/admin"):
            continue
        for method in methods:
            if method == "HEAD" or path == "/admin/login":
                continue
            actual.add((method, path))

    expected = set(PROTECTED_ADMIN_ROUTES)
    missing_from_test_list = actual - expected
    stale_in_test_list = expected - actual
    assert not missing_from_test_list, f"routes registered but not covered by this test: {missing_from_test_list}"
    assert not stale_in_test_list, f"routes in this test's list but no longer registered: {stale_in_test_list}"
