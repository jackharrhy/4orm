"""Pydantic models for JSON API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

# --- Auth ---


class AuthResponse(BaseModel):
    username: str
    display_name: str
    redirect: str


# --- Profile ---


class PageSummary(BaseModel):
    slug: str
    title: str
    is_public: bool
    layout: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileResponse(BaseModel):
    username: str
    display_name: str
    content: str
    content_format: str
    rendered_content: str
    custom_css: str
    custom_html: str
    layout: str
    pages: list[PageSummary]


class PageDetail(BaseModel):
    slug: str
    title: str
    content: str
    content_format: str
    rendered_content: str
    layout: str
    is_public: bool
    username: str
    display_name: str
    custom_css: str
    custom_html: str


# --- Homepage ---


class ProfileCard(BaseModel):
    username: str
    headline: str
    content: str
    content_format: str
    rendered_content: str
    accent_color: str
    border_style: str
    card_css: str


class ForumPostPreview(BaseModel):
    id: int
    thread_id: int
    thread_title: str
    author_username: str
    author_display_name: str
    rendered_content: str
    created_at: datetime | None = None


class HomepageResponse(BaseModel):
    cards: list[ProfileCard]
    recent_forum_posts: list[ForumPostPreview]


# --- Forum ---


class ForumThreadSummary(BaseModel):
    id: int
    title: str
    author_username: str
    author_display_name: str
    reply_count: int
    is_pinned: bool
    is_locked: bool
    last_reply_at: datetime | None = None
    created_at: datetime | None = None


class ForumThreadList(BaseModel):
    threads: list[ForumThreadSummary]
    total: int
    page: int
    total_pages: int


class ForumPost(BaseModel):
    id: int
    thread_id: int
    author_username: str
    author_display_name: str
    content: str
    content_format: str
    rendered_content: str
    quoted_post_id: int | None = None
    quoted_content: str | None = None
    quoted_content_format: str | None = None
    rendered_quoted_content: str | None = None
    quoted_author: str | None = None
    is_edited: bool
    author_signature: str | None = None
    rendered_signature: str | None = None
    created_at: datetime | None = None


class ForumThreadDetail(BaseModel):
    id: int
    title: str
    author_username: str
    author_display_name: str
    is_pinned: bool
    is_locked: bool
    custom_css: str
    custom_html: str
    created_at: datetime | None = None
    posts: list[ForumPost]
    total_posts: int
    page: int
    total_pages: int
    watching: bool


# --- Guestbook ---


class GuestbookEntry(BaseModel):
    id: int
    author_username: str
    author_display_name: str
    message: str
    created_at: datetime | None = None


class GuestbookResponse(BaseModel):
    owner_username: str
    entries: list[GuestbookEntry]
    can_post: bool


# --- Media ---


class MediaItem(BaseModel):
    id: int
    storage_path: str
    mime_type: str
    size_bytes: int
    alt_text: str | None = None


class MediaListResponse(BaseModel):
    items: list[MediaItem]
    storage_used: int
    storage_limit: int
    storage_pct: float


# --- Widgets ---


class CounterResponse(BaseModel):
    username: str
    total_views: int


class StatusResponse(BaseModel):
    username: str
    status_emoji: str
    status_text: str
    relative_time: str


class WebringNeighbor(BaseModel):
    username: str
    display_name: str


class WebringResponse(BaseModel):
    username: str
    prev: WebringNeighbor | None = None
    next: WebringNeighbor | None = None


class PlayerTrack(BaseModel):
    id: int
    title: str | None = None
    storage_path: str
    mime_type: str


class PlayerResponse(BaseModel):
    username: str
    tracks: list[PlayerTrack]


# --- Lineage ---


class LineageNode(BaseModel):
    username: str
    display_name: str
    children: list[LineageNode]


class LineageResponse(BaseModel):
    tree: list[LineageNode]


# --- Invites ---


class InviteInfo(BaseModel):
    code: str
    max_uses: int
    uses_count: int
    status: str
    redeemed_by: list[dict]


# --- Settings ---


class SettingsResponse(BaseModel):
    username: str
    display_name: str
    content: str
    content_format: str
    layout: str
    custom_css: str
    custom_html: str
    guestbook_css: str
    guestbook_html: str
    counter_css: str
    counter_html: str
    status_emoji: str
    status_text: str
    player_css: str
    player_html: str
    forum_signature: str
    in_webring: bool
    notifications_enabled: bool
    watch_all_threads: bool
    invites: list[InviteInfo]
    pages: list[PageSummary]
    media_items: list[MediaItem]
    playlist: list[PlayerTrack]


# --- Generic ---


class SuccessResponse(BaseModel):
    ok: bool = True
    message: str = "saved"


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str


class CreatedResponse(BaseModel):
    ok: bool = True
    id: int | None = None
    slug: str | None = None
    code: str | None = None
    redirect: str | None = None
