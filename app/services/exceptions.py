"""
Service-layer exceptions.

These are plain Python exceptions, not HTTP exceptions — services stay
usable from tests, scripts, or a future CLI, not just from a request
handler. Phase 3/4 routers will catch these and translate them to the
right HTTP status (404, 409, ...) via FastAPI exception handlers, in one
place, instead of every route doing its own try/except.
"""


class NotFoundError(LookupError):
    """Base class for 'the thing you asked for doesn't exist' errors."""


class WorkNotFoundError(NotFoundError):
    pass


class ChapterNotFoundError(NotFoundError):
    pass


class TagNotFoundError(NotFoundError):
    pass


class InvalidStateTransitionError(ValueError):
    """Raised when a publishing status transition isn't allowed."""


class DuplicateChapterNumberError(ValueError):
    """Raised when a chapter_number would collide with another chapter in the same work."""
