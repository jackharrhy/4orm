from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(32), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("display_name", String(80), nullable=False),
    Column("content", Text, nullable=False, server_default=""),
    Column("content_format", String(20), nullable=False, server_default="html"),
    Column("avatar_media_id", Integer, ForeignKey("media.id", ondelete="SET NULL")),
    Column("custom_css", Text, nullable=False, server_default=""),
    Column("custom_html", Text, nullable=False, server_default=""),
    Column("layout", String(20), nullable=False, server_default="default"),
    Column("guestbook_css", Text, nullable=False, server_default=""),
    Column("guestbook_html", Text, nullable=False, server_default=""),
    Column("counter_css", Text, nullable=False, server_default=""),
    Column("counter_html", Text, nullable=False, server_default=""),
    Column("in_webring", Boolean, nullable=False, server_default="0"),
    Column("status_emoji", String(10), nullable=False, server_default=""),
    Column("status_text", String(140), nullable=False, server_default=""),
    Column("status_updated_at", DateTime(timezone=True)),
    Column("status_css", Text, nullable=False, server_default=""),
    Column("status_html", Text, nullable=False, server_default=""),
    Column("player_css", Text, nullable=False, server_default=""),
    Column("player_html", Text, nullable=False, server_default=""),
    Column("forum_signature", Text, nullable=False, server_default=""),
    Column("is_admin", Boolean, nullable=False, server_default="0"),
    Column("has_accepted_trust", Boolean, nullable=False, server_default="0"),
    Column("notifications_enabled", Boolean, nullable=False, server_default="1"),
    Column("watch_all_threads", Boolean, nullable=False, server_default="0"),
    Column("is_disabled", Boolean, nullable=False, server_default="0"),
    Column("invited_by_user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("invite_id", Integer, ForeignKey("invites.id", ondelete="SET NULL")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

invites = Table(
    "invites",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(64), nullable=False, unique=True),
    Column(
        "created_by_user_id",
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("used_by_user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("max_uses", Integer, nullable=False, server_default="1"),
    Column("uses_count", Integer, nullable=False, server_default="0"),
    Column("expires_at", DateTime(timezone=True)),
    Column("disabled", Boolean, nullable=False, server_default="0"),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("used_at", DateTime(timezone=True)),
    CheckConstraint("max_uses >= 1", name="ck_invites_max_uses"),
)

password_reset_tokens = Table(
    "password_reset_tokens",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    Column("created_by_user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

pages = Table(
    "pages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("slug", String(80), nullable=False),
    Column("title", String(140), nullable=False),
    Column("content", Text, nullable=False, server_default=""),
    Column("content_format", String(20), nullable=False, server_default="html"),
    Column("layout", String(20), nullable=False, server_default="default"),
    Column("is_public", Boolean, nullable=False, server_default="1"),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    UniqueConstraint("user_id", "slug", name="uq_pages_user_slug"),
)

media = Table(
    "media",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("storage_path", String(255), nullable=False),
    Column("mime_type", String(120), nullable=False),
    Column("width", Integer),
    Column("height", Integer),
    Column("size_bytes", Integer, nullable=False, server_default="0"),
    Column("alt_text", String(255), nullable=False, server_default=""),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

guestbook_entries = Table(
    "guestbook_entries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "author_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("message", Text, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)


visitor_counters = Table(
    "visitor_counters",
    metadata,
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("total_views", Integer, nullable=False, server_default="0"),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

forum_threads = Table(
    "forum_threads",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "author_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("title", String(200), nullable=False),
    Column("custom_css", Text, nullable=False, server_default=""),
    Column("custom_html", Text, nullable=False, server_default=""),
    Column("is_pinned", Boolean, nullable=False, server_default="0"),
    Column("is_locked", Boolean, nullable=False, server_default="0"),
    Column("reply_count", Integer, nullable=False, server_default="0"),
    Column("last_reply_at", DateTime(timezone=True), server_default=func.now()),
    Column("last_reply_by_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

forum_posts = Table(
    "forum_posts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "thread_id",
        Integer,
        ForeignKey("forum_threads.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "author_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("content", Text, nullable=False),
    Column("content_format", String(20), nullable=False, server_default="bbcode"),
    Column("quoted_post_id", Integer),
    Column("quoted_content", Text),
    Column("quoted_content_format", String(20)),
    Column("quoted_author", String(80)),
    Column("is_edited", Boolean, nullable=False, server_default="0"),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

playlist_items = Table(
    "playlist_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "media_id", Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False
    ),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("title", String(200)),
)

chat_messages = Table(
    "chat_messages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "author_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("message", Text, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

push_subscriptions = Table(
    "push_subscriptions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("device_id", String(64), nullable=False),
    Column("device_name", String(100), nullable=False, server_default=""),
    Column("endpoint", Text, nullable=False),
    Column("p256dh_key", Text, nullable=False),
    Column("auth_key", Text, nullable=False),
    UniqueConstraint("user_id", "device_id", name="uq_push_user_device"),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

thread_watchers = Table(
    "thread_watchers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "thread_id",
        Integer,
        ForeignKey("forum_threads.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    UniqueConstraint("user_id", "thread_id", name="uq_thread_watchers"),
)

profile_cards = Table(
    "profile_cards",
    metadata,
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("headline", String(120), nullable=False, server_default=""),
    Column("content", Text, nullable=False, server_default=""),
    Column("content_format", String(20), nullable=False, server_default="html"),
    Column("accent_color", String(20), nullable=False, server_default="#00ffff"),
    Column("border_style", String(20), nullable=False, server_default="outset"),
    Column("card_css", Text, nullable=False, server_default=""),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

oauth2_clients = Table(
    "oauth2_clients",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("client_id", String(48), nullable=False, unique=True),
    Column("client_secret", String(120), nullable=False, server_default=""),
    Column("client_name", String(120), nullable=False),
    Column("redirect_uris", Text, nullable=False, server_default=""),
    Column("scope", Text, nullable=False, server_default=""),
    Column("grant_types", Text, nullable=False, server_default="authorization_code"),
    Column("response_types", Text, nullable=False, server_default="code"),
    Column(
        "token_endpoint_auth_method",
        String(48),
        nullable=False,
        server_default="client_secret_basic",
    ),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

oauth2_authorization_codes = Table(
    "oauth2_authorization_codes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", String(120), nullable=False, unique=True),
    Column("client_id", String(48), nullable=False),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("redirect_uri", Text, nullable=False, server_default=""),
    Column("scope", Text, nullable=False, server_default=""),
    Column("nonce", String(120)),
    Column("code_challenge", Text),
    Column("code_challenge_method", String(10)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

oauth2_tokens = Table(
    "oauth2_tokens",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("client_id", String(48), nullable=False),
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("token_type", String(40), nullable=False, server_default="bearer"),
    Column("access_token", String(255), nullable=False, unique=True),
    Column("refresh_token", String(255), unique=True),
    Column("scope", Text, nullable=False, server_default=""),
    Column("issued_at", Integer, nullable=False),
    Column("expires_in", Integer, nullable=False, server_default="3600"),
    Column("revoked", Boolean, nullable=False, server_default="0"),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)


def create_all(engine):
    metadata.create_all(engine)
