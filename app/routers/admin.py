"""
Admin CMS routes.

Every route except /admin/login is protected with
`dependencies=[Depends(require_admin)]` — explicit per-route rather than
applied once at the router level, matching the rest of this codebase's
style of being explicit over clever (see app/routers/public.py). Every
POST verifies a CSRF token before touching anything. Routers stay thin:
form parsing, auth, and CSRF live here; business rules stay in
WorkService/ChapterService.
"""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import flash, get_csrf_token, login_rate_limiter, require_admin, verify_csrf, verify_password
from app.core.templating import templates
from app.db.database import get_db
from app.models.enums import PublishStatus, WorkType
from app.routers.public import segment_for
from app.schemas.chapter import ChapterCreate, ChapterUpdate
from app.schemas.work import WorkCreate, WorkUpdate
from app.services.chapter_service import ChapterService
from app.services.exceptions import (
    ChapterNotFoundError,
    DuplicateChapterNumberError,
    InvalidStateTransitionError,
    WorkNotFoundError,
)
from app.services.work_service import WorkService

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()
logger = logging.getLogger("shrine.admin")


def _field_errors(exc: ValidationError) -> dict[str, str]:
    """Flatten a Pydantic ValidationError into {field: message} for inline form display."""
    errors: dict[str, str] = {}
    for err in exc.errors():
        field = str(err["loc"][-1]) if err["loc"] else "form"
        errors[field] = err["msg"]
    return errors


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _split_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


# ------------------------------------------------------------------- auth


@router.get("/login")
def login_form(request: Request):
    if request.session.get("is_admin"):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"csrf_token": get_csrf_token(request)})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    ip = _client_ip(request)

    if login_rate_limiter.is_locked_out(ip):
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"csrf_token": get_csrf_token(request), "error": "Too many failed attempts. Try again in a few minutes."},
            status_code=429,
        )

    valid = username == settings.ADMIN_USERNAME and verify_password(password, settings.ADMIN_PASSWORD_HASH)
    if not valid:
        login_rate_limiter.record_failure(ip)
        logger.warning("Failed admin login attempt from %s", ip)
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"csrf_token": get_csrf_token(request), "error": "Incorrect username or password."},
            status_code=401,
        )

    login_rate_limiter.record_success(ip)
    request.session["is_admin"] = True
    logger.info("Admin login succeeded from %s", ip)
    flash(request, "Welcome back.")
    return RedirectResponse("/admin", status_code=303)


@router.post("/logout", dependencies=[Depends(require_admin)])
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    logger.info("Admin logout from %s", _client_ip(request))
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# -------------------------------------------------------------- dashboard


@router.get("", dependencies=[Depends(require_admin)])
def dashboard(request: Request, db: Session = Depends(get_db)):
    work_service = WorkService(db)
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "counts": work_service.count_by_status(),
            "recent_works": work_service.list_for_admin(limit=8),
            "csrf_token": get_csrf_token(request),
        },
    )


# ------------------------------------------------------------------ works


@router.get("/works", dependencies=[Depends(require_admin)])
def admin_works_list(request: Request, db: Session = Depends(get_db), status: str | None = None):
    status_filter: PublishStatus | None = None
    if status:
        try:
            status_filter = PublishStatus(status)
        except ValueError:
            status_filter = None

    works = WorkService(db).list_for_admin(status=status_filter, limit=200)
    return templates.TemplateResponse(
        request,
        "admin/works.html",
        {"works": works, "status_filter": status_filter, "csrf_token": get_csrf_token(request)},
    )


@router.get("/works/new", dependencies=[Depends(require_admin)])
def new_work_form(request: Request):
    return templates.TemplateResponse(
        request,
        "admin/work_form.html",
        {
            "work": None,
            "chapters": [],
            "work_types": list(WorkType),
            "csrf_token": get_csrf_token(request),
            "errors": {},
            "form_values": {
                "title": "",
                "work_type": "",
                "description": "",
                "cover_image": "",
                "slug": "",
                "tag_names": "",
            },
        },
    )


@router.post("/works/new", dependencies=[Depends(require_admin)])
def create_work(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    title: str = Form(...),
    work_type: str = Form(...),
    description: str = Form(""),
    cover_image: str = Form(""),
    slug: str = Form(""),
    tag_names: str = Form(""),
):
    verify_csrf(request, csrf_token)
    form_values = {
        "title": title,
        "work_type": work_type,
        "description": description,
        "cover_image": cover_image,
        "slug": slug,
        "tag_names": tag_names,
    }

    try:
        data = WorkCreate(
            title=title,
            type=work_type,
            description=description.strip() or None,
            cover_image=cover_image.strip() or None,
            slug=slug.strip() or None,
            tag_names=_split_tags(tag_names),
        )
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "admin/work_form.html",
            {
                "work": None,
                "chapters": [],
                "work_types": list(WorkType),
                "csrf_token": get_csrf_token(request),
                "errors": _field_errors(exc),
                "form_values": form_values,
            },
            status_code=422,
        )

    work = WorkService(db).create_work(data)
    logger.info("Work created: id=%s title=%r type=%s", work.id, work.title, work.type.value)
    note = ""
    if data.slug and data.slug != work.slug:
        note = f" (the URL \u2018{data.slug}\u2019 was already taken \u2014 used \u2018{work.slug}\u2019 instead)"
    flash(request, f'"{work.title}" created as a draft.{note}')
    return RedirectResponse(f"/admin/works/{work.id}/edit", status_code=303)


@router.get("/works/{work_id}/edit", dependencies=[Depends(require_admin)])
def edit_work_form(work_id: int, request: Request, db: Session = Depends(get_db)):
    work_service = WorkService(db)
    try:
        work = work_service.get_for_admin(work_id)
    except WorkNotFoundError:
        flash(request, "That work no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)

    return templates.TemplateResponse(
        request,
        "admin/work_form.html",
        {
            "work": work,
            "segment": segment_for(work.type),
            "chapters": ChapterService(db).list_for_admin(work_id),
            "work_types": list(WorkType),
            "csrf_token": get_csrf_token(request),
            "errors": {},
            "form_values": {
                "title": work.title,
                "work_type": work.type.value,
                "description": work.description or "",
                "cover_image": work.cover_image or "",
                "tag_names": ", ".join(tag.name for tag in work.tags),
            },
        },
    )


@router.post("/works/{work_id}/edit", dependencies=[Depends(require_admin)])
def update_work(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    title: str = Form(...),
    work_type: str = Form(...),
    description: str = Form(""),
    cover_image: str = Form(""),
    tag_names: str = Form(""),
):
    verify_csrf(request, csrf_token)
    work_service = WorkService(db)
    try:
        work = work_service.get_for_admin(work_id)
    except WorkNotFoundError:
        flash(request, "That work no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)

    form_values = {
        "title": title,
        "work_type": work_type,
        "description": description,
        "cover_image": cover_image,
        "tag_names": tag_names,
    }

    try:
        data = WorkUpdate(
            title=title,
            type=work_type,
            description=description.strip() or None,
            cover_image=cover_image.strip() or None,
            tag_names=_split_tags(tag_names),
        )
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "admin/work_form.html",
            {
                "work": work,
                "segment": segment_for(work.type),
                "chapters": ChapterService(db).list_for_admin(work_id),
                "work_types": list(WorkType),
                "csrf_token": get_csrf_token(request),
                "errors": _field_errors(exc),
                "form_values": form_values,
            },
            status_code=422,
        )

    work_service.update_work(work_id, data)
    flash(request, "Work saved.")
    return RedirectResponse(f"/admin/works/{work_id}/edit", status_code=303)


def _work_status_action(work_id: int, request: Request, db: Session, action: str) -> RedirectResponse:
    work_service = WorkService(db)
    try:
        work_service.get_for_admin(work_id)  # 404 early if it's already gone
        if action == "publish":
            work_service.publish(work_id)
            logger.info("Work published: id=%s", work_id)
            flash(request, "Work published.")
        elif action == "unpublish":
            work_service.unpublish(work_id)
            logger.info("Work unpublished: id=%s", work_id)
            flash(request, "Work unpublished \u2014 it's a draft again.")
        elif action == "archive":
            work_service.archive(work_id)
            logger.info("Work archived: id=%s", work_id)
            flash(request, "Work archived.")
    except WorkNotFoundError:
        flash(request, "That work no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)
    except InvalidStateTransitionError as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(f"/admin/works/{work_id}/edit", status_code=303)


@router.post("/works/{work_id}/publish", dependencies=[Depends(require_admin)])
def publish_work(work_id: int, request: Request, db: Session = Depends(get_db), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    return _work_status_action(work_id, request, db, "publish")


@router.post("/works/{work_id}/unpublish", dependencies=[Depends(require_admin)])
def unpublish_work(work_id: int, request: Request, db: Session = Depends(get_db), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    return _work_status_action(work_id, request, db, "unpublish")


@router.post("/works/{work_id}/archive", dependencies=[Depends(require_admin)])
def archive_work(work_id: int, request: Request, db: Session = Depends(get_db), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    return _work_status_action(work_id, request, db, "archive")


@router.post("/works/{work_id}/delete", dependencies=[Depends(require_admin)])
def delete_work(work_id: int, request: Request, db: Session = Depends(get_db), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    work_service = WorkService(db)
    try:
        work = work_service.get_for_admin(work_id)
        title = work.title
        work_service.delete_work(work_id)
        logger.warning("Work deleted: id=%s title=%r", work_id, title)
        flash(request, f'"{title}" deleted, along with its chapters.')
    except WorkNotFoundError:
        flash(request, "That work no longer exists.", "error")
    return RedirectResponse("/admin/works", status_code=303)


# --------------------------------------------------------------- chapters


@router.get("/works/{work_id}/chapters/new", dependencies=[Depends(require_admin)])
def new_chapter_form(work_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        work = WorkService(db).get_for_admin(work_id)
    except WorkNotFoundError:
        flash(request, "That work no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)

    return templates.TemplateResponse(
        request,
        "admin/chapter_form.html",
        {
            "work": work,
            "chapter": None,
            "csrf_token": get_csrf_token(request),
            "errors": {},
            "form_values": {"title": "", "chapter_number": "", "content": "", "slug": ""},
        },
    )


@router.post("/works/{work_id}/chapters/new", dependencies=[Depends(require_admin)])
def create_chapter(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    title: str = Form(...),
    chapter_number: str = Form(...),
    content: str = Form(""),
    slug: str = Form(""),
):
    verify_csrf(request, csrf_token)
    try:
        work = WorkService(db).get_for_admin(work_id)
    except WorkNotFoundError:
        flash(request, "That work no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)

    form_values = {"title": title, "chapter_number": chapter_number, "content": content, "slug": slug}

    try:
        data = ChapterCreate(title=title, chapter_number=chapter_number, content=content, slug=slug.strip() or None)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "admin/chapter_form.html",
            {
                "work": work,
                "chapter": None,
                "csrf_token": get_csrf_token(request),
                "errors": _field_errors(exc),
                "form_values": form_values,
            },
            status_code=422,
        )

    try:
        chapter = ChapterService(db).create_chapter(work_id, data)
    except DuplicateChapterNumberError as exc:
        return templates.TemplateResponse(
            request,
            "admin/chapter_form.html",
            {
                "work": work,
                "chapter": None,
                "csrf_token": get_csrf_token(request),
                "errors": {"chapter_number": str(exc)},
                "form_values": form_values,
            },
            status_code=422,
        )

    flash(request, f'"{chapter.title}" created as a draft.')
    logger.info("Chapter created: id=%s title=%r work_id=%s", chapter.id, chapter.title, work_id)
    return RedirectResponse(f"/admin/chapters/{chapter.id}/edit", status_code=303)


@router.get("/chapters/{chapter_id}/edit", dependencies=[Depends(require_admin)])
def edit_chapter_form(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    chapter_service = ChapterService(db)
    try:
        chapter = chapter_service.get_for_admin(chapter_id)
    except ChapterNotFoundError:
        flash(request, "That chapter no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)

    work = WorkService(db).get_for_admin(chapter.work_id)
    return templates.TemplateResponse(
        request,
        "admin/chapter_form.html",
        {
            "work": work,
            "chapter": chapter,
            "csrf_token": get_csrf_token(request),
            "errors": {},
            "form_values": {
                "title": chapter.title,
                "chapter_number": str(chapter.chapter_number),
                "content": chapter.content,
                "slug": chapter.slug,
            },
        },
    )


@router.post("/chapters/{chapter_id}/edit", dependencies=[Depends(require_admin)])
def update_chapter(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    title: str = Form(...),
    chapter_number: str = Form(...),
    content: str = Form(""),
):
    verify_csrf(request, csrf_token)
    chapter_service = ChapterService(db)
    try:
        chapter = chapter_service.get_for_admin(chapter_id)
    except ChapterNotFoundError:
        flash(request, "That chapter no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)

    work = WorkService(db).get_for_admin(chapter.work_id)
    form_values = {"title": title, "chapter_number": chapter_number, "content": content}

    try:
        data = ChapterUpdate(title=title, chapter_number=chapter_number, content=content)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "admin/chapter_form.html",
            {
                "work": work,
                "chapter": chapter,
                "csrf_token": get_csrf_token(request),
                "errors": _field_errors(exc),
                "form_values": form_values,
            },
            status_code=422,
        )

    try:
        chapter_service.update_chapter(chapter_id, data)
    except DuplicateChapterNumberError as exc:
        return templates.TemplateResponse(
            request,
            "admin/chapter_form.html",
            {
                "work": work,
                "chapter": chapter,
                "csrf_token": get_csrf_token(request),
                "errors": {"chapter_number": str(exc)},
                "form_values": form_values,
            },
            status_code=422,
        )

    flash(request, "Chapter saved.")
    return RedirectResponse(f"/admin/chapters/{chapter_id}/edit", status_code=303)


def _chapter_status_action(chapter_id: int, request: Request, db: Session, action: str) -> RedirectResponse:
    chapter_service = ChapterService(db)
    try:
        chapter_service.get_for_admin(chapter_id)  # 404 early if it's already gone
        if action == "publish":
            chapter_service.publish(chapter_id)
            logger.info("Chapter published: id=%s", chapter_id)
            flash(request, "Chapter published.")
        elif action == "unpublish":
            chapter_service.unpublish(chapter_id)
            logger.info("Chapter unpublished: id=%s", chapter_id)
            flash(request, "Chapter unpublished \u2014 it's a draft again.")
        elif action == "archive":
            chapter_service.archive(chapter_id)
            logger.info("Chapter archived: id=%s", chapter_id)
            flash(request, "Chapter archived.")
    except ChapterNotFoundError:
        flash(request, "That chapter no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)
    except InvalidStateTransitionError as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(f"/admin/chapters/{chapter_id}/edit", status_code=303)


@router.post("/chapters/{chapter_id}/publish", dependencies=[Depends(require_admin)])
def publish_chapter(chapter_id: int, request: Request, db: Session = Depends(get_db), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    return _chapter_status_action(chapter_id, request, db, "publish")


@router.post("/chapters/{chapter_id}/unpublish", dependencies=[Depends(require_admin)])
def unpublish_chapter(chapter_id: int, request: Request, db: Session = Depends(get_db), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    return _chapter_status_action(chapter_id, request, db, "unpublish")


@router.post("/chapters/{chapter_id}/archive", dependencies=[Depends(require_admin)])
def archive_chapter(chapter_id: int, request: Request, db: Session = Depends(get_db), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    return _chapter_status_action(chapter_id, request, db, "archive")


@router.post("/chapters/{chapter_id}/delete", dependencies=[Depends(require_admin)])
def delete_chapter(chapter_id: int, request: Request, db: Session = Depends(get_db), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    chapter_service = ChapterService(db)
    try:
        chapter = chapter_service.get_for_admin(chapter_id)
        work_id, title = chapter.work_id, chapter.title
        chapter_service.delete_chapter(chapter_id)
        logger.warning("Chapter deleted: id=%s title=%r work_id=%s", chapter_id, title, work_id)
        flash(request, f'"{title}" deleted.')
        return RedirectResponse(f"/admin/works/{work_id}/edit", status_code=303)
    except ChapterNotFoundError:
        flash(request, "That chapter no longer exists.", "error")
        return RedirectResponse("/admin/works", status_code=303)
