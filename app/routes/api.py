"""Stable, machine-oriented API routes."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select

import app.deps as deps
from app.deps import clean_filename, get_engine, require_api_user, unique_filename
from app.models import (
    ApiPage,
    ApiPageList,
    MediaItem,
    MediaListResponse,
    MeResponse,
    PageWriteRequest,
    SuccessResponse,
)
from app.queries.media import (
    create_media,
    delete_media_for_user,
    get_media_for_user,
    list_media_for_user,
)
from app.queries.pages import (
    delete_user_page,
    get_user_page,
    list_pages_for_user,
    upsert_user_page,
)
from app.schema import media

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


def _page_response(page) -> ApiPage:
    return ApiPage(
        slug=page["slug"],
        title=page["title"],
        content=page["content"] or "",
        content_format=page["content_format"] or "html",
        layout=page["layout"] or "default",
        is_public=bool(page["is_public"]),
        created_at=page.get("created_at"),
        updated_at=page.get("updated_at"),
    )


def _media_response(item) -> MediaItem:
    return MediaItem(
        id=item["id"],
        storage_path=item["storage_path"],
        mime_type=item["mime_type"],
        size_bytes=item["size_bytes"],
        alt_text=item.get("alt_text"),
    )


@router.get("/me", response_model=MeResponse, operation_id="getMe")
def api_me(user=Depends(require_api_user)):
    return MeResponse(username=user["username"], display_name=user["display_name"])


@router.get("/pages", response_model=ApiPageList, operation_id="listPages")
def api_pages(request: Request, user=Depends(require_api_user)):
    with get_engine(request).begin() as conn:
        pages = list_pages_for_user(conn, user["id"])
        full_pages = [get_user_page(conn, user["id"], page["slug"]) for page in pages]
    return ApiPageList(pages=[_page_response(page) for page in full_pages])


@router.get("/pages/{slug}", response_model=ApiPage, operation_id="getPage")
def api_page(request: Request, slug: str, user=Depends(require_api_user)):
    with get_engine(request).begin() as conn:
        page = get_user_page(conn, user["id"], slug)
    if not page:
        raise HTTPException(404, detail="page not found")
    return _page_response(page)


@router.put("/pages/{slug}", response_model=ApiPage, operation_id="publishPage")
def api_page_publish(
    request: Request,
    slug: str,
    body: PageWriteRequest,
    user=Depends(require_api_user),
):
    if not slug or len(slug) > 80 or "/" in slug or slug in {".", ".."}:
        raise HTTPException(422, detail="invalid page slug")

    with get_engine(request).begin() as conn:
        page = upsert_user_page(
            conn,
            user["id"],
            slug,
            title=body.title,
            content=body.content,
            content_format=body.content_format,
            layout=body.layout,
            is_public=body.is_public,
        )
    return _page_response(page)


@router.delete(
    "/pages/{slug}", response_model=SuccessResponse, operation_id="deletePage"
)
def api_page_delete(request: Request, slug: str, user=Depends(require_api_user)):
    with get_engine(request).begin() as conn:
        if not get_user_page(conn, user["id"], slug):
            raise HTTPException(404, detail="page not found")
        delete_user_page(conn, user["id"], slug)
    return SuccessResponse(message="page deleted")


@router.get("/media", response_model=MediaListResponse, operation_id="listMedia")
def api_media(request: Request, user=Depends(require_api_user)):
    with get_engine(request).begin() as conn:
        items = list_media_for_user(conn, user["id"])
        storage_used = conn.execute(
            select(func.coalesce(func.sum(media.c.size_bytes), 0)).where(
                media.c.user_id == user["id"]
            )
        ).scalar()
    storage_pct = (
        storage_used / deps.MAX_STORAGE_PER_USER * 100
        if deps.MAX_STORAGE_PER_USER
        else 0
    )
    return MediaListResponse(
        items=[_media_response(item) for item in items],
        storage_used=storage_used,
        storage_limit=deps.MAX_STORAGE_PER_USER,
        storage_pct=storage_pct,
    )


@router.post("/media", response_model=MediaItem, operation_id="uploadMedia")
async def api_media_upload(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_api_user),
):
    user_upload_dir = deps.UPLOADS_DIR / user["username"]
    user_upload_dir.mkdir(parents=True, exist_ok=True)
    final_name = unique_filename(
        user_upload_dir, clean_filename(file.filename or "file")
    )
    rel_path = f"{user['username']}/{final_name}"
    content = await file.read()
    if len(content) > deps.MAX_UPLOAD_BYTES:
        raise HTTPException(400, detail="file too big")

    with get_engine(request).begin() as conn:
        current_usage = conn.execute(
            select(func.coalesce(func.sum(media.c.size_bytes), 0)).where(
                media.c.user_id == user["id"]
            )
        ).scalar()
        if current_usage + len(content) > deps.MAX_STORAGE_PER_USER:
            raise HTTPException(400, detail="storage full")

    disk_path = deps.UPLOADS_DIR / rel_path
    disk_path.write_bytes(content)
    try:
        with get_engine(request).begin() as conn:
            create_media(
                conn,
                user_id=user["id"],
                storage_path=rel_path,
                mime_type=file.content_type or "application/octet-stream",
                size_bytes=len(content),
            )
            item = (
                conn.execute(select(media).where(media.c.storage_path == rel_path))
                .mappings()
                .first()
            )
    except Exception:
        disk_path.unlink(missing_ok=True)
        raise
    return _media_response(item)


@router.delete(
    "/media/{media_id}", response_model=SuccessResponse, operation_id="deleteMedia"
)
def api_media_delete(request: Request, media_id: int, user=Depends(require_api_user)):
    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, user["id"], media_id)
        if not item:
            raise HTTPException(404, detail="media not found")
        delete_media_for_user(conn, user["id"], media_id)
    (deps.UPLOADS_DIR / item["storage_path"]).unlink(missing_ok=True)
    return SuccessResponse(message="media deleted")
