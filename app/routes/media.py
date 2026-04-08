"""Media library routes."""

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

import app.deps as deps
from app.deps import clean_filename, current_user, get_engine, is_htmx, templates
from app.queries.media import (
    create_media,
    delete_media_for_user,
    get_media_for_user,
    list_media_for_user,
    update_media_alt_text,
    update_media_storage_path,
)
from app.schema import media

router = APIRouter()


@router.get("/settings/media", response_class=HTMLResponse)
def settings_media_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        items = list_media_for_user(conn, me["id"])
        storage_used = conn.execute(
            select(func.coalesce(func.sum(media.c.size_bytes), 0)).where(
                media.c.user_id == me["id"]
            )
        ).scalar()
    storage_pct = (
        (storage_used / deps.MAX_STORAGE_PER_USER * 100)
        if deps.MAX_STORAGE_PER_USER
        else 0
    )
    return templates.TemplateResponse(
        request,
        "settings_media.html",
        {
            "me": me,
            "items": items,
            "storage_used": storage_used,
            "storage_limit": deps.MAX_STORAGE_PER_USER,
            "storage_pct": storage_pct,
        },
    )


@router.post("/settings/media/upload")
async def settings_media_upload(
    request: Request, file: UploadFile = File(...), filename: str = Form("")
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    username = me["username"]
    user_upload_dir = deps.UPLOADS_DIR / username
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    chosen_name = filename.strip() or (file.filename or "file")
    final_name = clean_filename(chosen_name)
    original_ext = Path(file.filename or "").suffix.lower()
    if original_ext and Path(final_name).suffix.lower() != original_ext:
        final_name = f"{Path(final_name).stem}{original_ext}"

    rel_path = f"{username}/{final_name}"
    disk_path = deps.UPLOADS_DIR / rel_path

    # Avoid collisions by suffixing -2, -3, ...
    if disk_path.exists():
        base = Path(final_name).stem
        ext = Path(final_name).suffix
        i = 2
        while True:
            candidate = f"{base}-{i}{ext}"
            candidate_path = user_upload_dir / candidate
            if not candidate_path.exists():
                final_name = candidate
                rel_path = f"{username}/{final_name}"
                disk_path = candidate_path
                break
            i += 1

    content = await file.read()
    if len(content) > deps.MAX_UPLOAD_BYTES:
        return RedirectResponse(url="/settings/media?error=too_big", status_code=303)

    # Check per-user storage limit
    with get_engine(request).begin() as conn:
        current_usage = conn.execute(
            select(func.coalesce(func.sum(media.c.size_bytes), 0)).where(
                media.c.user_id == me["id"]
            )
        ).scalar()
    if current_usage + len(content) > deps.MAX_STORAGE_PER_USER:
        return RedirectResponse(
            url="/settings/media?error=storage_full", status_code=303
        )

    disk_path.write_bytes(content)

    with get_engine(request).begin() as conn:
        create_media(
            conn,
            user_id=me["id"],
            storage_path=rel_path,
            mime_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
        )
        if is_htmx(request):
            item = (
                conn.execute(select(media).where(media.c.storage_path == rel_path))
                .mappings()
                .first()
            )
            return templates.TemplateResponse(
                request, "fragments/media_card.html", {"item": item}
            )

    return RedirectResponse(url="/settings/media", status_code=303)


def _media_card_response(request: Request, me, media_id):
    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
    if item and is_htmx(request):
        return templates.TemplateResponse(
            request, "fragments/media_card.html", {"item": item}
        )
    return RedirectResponse(url="/settings/media", status_code=303)


@router.post("/settings/media/{media_id}/alt")
def settings_media_alt(request: Request, media_id: int, alt_text: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
        if not item:
            raise HTTPException(404)
        update_media_alt_text(conn, me["id"], media_id, alt_text)
    return _media_card_response(request, me, media_id)


@router.post("/settings/media/{media_id}/delete")
def settings_media_delete(request: Request, media_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
        if not item:
            raise HTTPException(404)
        delete_media_for_user(conn, me["id"], media_id)
    disk_path = deps.UPLOADS_DIR / item["storage_path"]
    if disk_path.exists():
        disk_path.unlink()
    if is_htmx(request):
        return HTMLResponse("")
    return RedirectResponse(url="/settings/media", status_code=303)


@router.post("/settings/media/{media_id}/rename")
def settings_media_rename(request: Request, media_id: int, filename: str = Form(...)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    username = me["username"]
    user_upload_dir = deps.UPLOADS_DIR / username
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
        if not item:
            raise HTTPException(404)

        new_name = clean_filename(filename)
        old_path = deps.UPLOADS_DIR / item["storage_path"]
        old_ext = old_path.suffix.lower()
        if old_ext and Path(new_name).suffix.lower() != old_ext:
            new_name = f"{Path(new_name).stem}{old_ext}"

        new_path = user_upload_dir / new_name
        if new_path.exists() and new_path != old_path:
            base = Path(new_name).stem
            ext = Path(new_name).suffix
            i = 2
            while True:
                candidate = user_upload_dir / f"{base}-{i}{ext}"
                if not candidate.exists():
                    new_path = candidate
                    break
                i += 1

        if old_path.exists() and old_path != new_path:
            old_path.rename(new_path)

        rel_path = f"{username}/{new_path.name}"
        update_media_storage_path(conn, me["id"], media_id, rel_path)

    return _media_card_response(request, me, media_id)
