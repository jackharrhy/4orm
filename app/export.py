import io
import re
import zipfile
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.rendering import (
    build_raw_html,
    render_content,
    render_forum_post,
    render_signature,
)
from app.schema import forum_posts, forum_threads, media, pages, users


def _rewrite_media_paths(content: str, username: str, prefix: str) -> str:
    """Rewrite /uploads/{username}/file.png to {prefix}/file.png."""
    return re.sub(
        rf"/uploads/{re.escape(username)}/",
        f"{prefix}/",
        content,
    )


def _rewrite_all_media_paths(content: str, base: str) -> str:
    """Rewrite /uploads/{any_user}/file.png to {base}/users/{user}/uploads/file.png."""
    return re.sub(
        r"/uploads/([^/]+)/",
        rf"{base}/users/\1/uploads/",
        content,
    )


def _render_export_page(
    env: Environment,
    title: str,
    content_html: str,
    custom_css: str,
    custom_html: str,
    layout: str,
    css_path: str,
    site_url: str,
    username: str,
) -> str:
    """Render a single export page, rewriting media paths."""
    # Determine uploads prefix from css_path
    if css_path == "style.css":
        uploads_prefix = "uploads"
    else:
        uploads_prefix = "../uploads"

    content_html = _rewrite_media_paths(content_html, username, uploads_prefix)
    custom_css = _rewrite_media_paths(custom_css, username, uploads_prefix)
    custom_html = _rewrite_media_paths(custom_html, username, uploads_prefix)

    if layout == "raw":
        return build_raw_html(content_html, custom_css, custom_html)

    tmpl = env.get_template("export_base.html")
    return tmpl.render(
        title=title,
        content=content_html,
        custom_css=custom_css,
        custom_html=custom_html,
        css_path=css_path,
        site_url=site_url,
    )


def build_export_zip(
    conn: Connection,
    username: str,
    uploads_dir: str | Path,
    style_css_path: str | Path,
    site_url: str,
    templates_dir: str | Path,
) -> bytes:
    """Build a zip archive of a user's entire site and return raw bytes."""
    # 1. Fetch user
    row = conn.execute(select(users).where(users.c.username == username)).first()
    if row is None:
        raise ValueError(f"User not found: {username}")
    user = row._mapping

    # 2. Fetch public pages
    page_rows = conn.execute(
        select(pages)
        .where(pages.c.user_id == user["id"], pages.c.is_public == True)  # noqa: E712
        .order_by(pages.c.created_at)
    ).fetchall()

    # 3. Fetch media paths
    media_rows = conn.execute(
        select(media.c.storage_path).where(media.c.user_id == user["id"])
    ).fetchall()

    # 4. Jinja2 environment
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=False,
    )

    prefix = f"{username}-export"

    # 5. Build zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # --- Profile index.html ---
        rendered_content = render_content(user["content"], user["content_format"])
        layout = user["layout"] or "default"

        if layout == "default" or layout == "":
            # Build page links
            page_links = ""
            if page_rows:
                items = "".join(
                    f'<li><a href="pages/{p._mapping["slug"]}.html">'
                    f"{escape(p._mapping['title'])}</a></li>"
                    for p in page_rows
                )
                page_links = f"<h2>pages</h2><ul>{items}</ul>"
            index_content = (
                f'<section class="panel">'
                f"<h1>{escape(user['display_name'])}</h1>"
                f"{rendered_content}"
                f"{page_links}"
                f"</section>"
            )
        elif layout == "simple":
            index_content = rendered_content
        elif layout == "cssonly":
            index_content = ""
        elif layout == "raw":
            index_content = rendered_content
        else:
            index_content = rendered_content

        index_html = _render_export_page(
            env,
            escape(user["display_name"]),
            index_content,
            user["custom_css"],
            user["custom_html"],
            layout,
            "style.css",
            site_url,
            username,
        )
        zf.writestr(f"{prefix}/index.html", index_html)

        # --- Pages ---
        for p in page_rows:
            pm = p._mapping
            page_rendered = render_content(pm["content"], pm["content_format"])
            page_layout = pm["layout"] or "default"

            if page_layout == "default" or page_layout == "":
                page_content = (
                    f'<article class="panel content-html">'
                    f"<h1>{escape(pm['title'])}</h1>"
                    f'<p class="muted">by <a href="../index.html">'
                    f"{escape(user['display_name'])}</a></p>"
                    f"<hr />"
                    f"{page_rendered}"
                    f"</article>"
                )
            elif page_layout == "simple":
                page_content = page_rendered
            elif page_layout == "cssonly":
                page_content = ""
            elif page_layout == "raw":
                page_content = page_rendered
            else:
                page_content = page_rendered

            page_html = _render_export_page(
                env,
                escape(pm["title"]),
                page_content,
                user["custom_css"],
                user["custom_html"],
                page_layout,
                "../style.css",
                site_url,
                username,
            )
            zf.writestr(f"{prefix}/pages/{pm['slug']}.html", page_html)

        # --- Uploads ---
        uploads_path = Path(uploads_dir)
        for mrow in media_rows:
            storage_path = mrow._mapping["storage_path"]
            # storage_path is like "{username}/filename.png"
            file_path = uploads_path / storage_path
            filename = Path(storage_path).name
            if file_path.exists():
                zf.write(file_path, f"{prefix}/uploads/{filename}")

        # --- style.css ---
        css_path = Path(style_css_path)
        if css_path.exists():
            zf.write(css_path, f"{prefix}/style.css")

    return buf.getvalue()


def _render_forum_thread_html(
    env: Environment,
    thread,
    posts: list,
    site_url: str,
) -> str:
    """Render a forum thread with all its posts as a static HTML page."""
    post_blocks = []
    for p in posts:
        rendered = render_forum_post(p["content"], p["content_format"])
        sig = render_signature(p.get("author_signature") or "")

        quote_html = ""
        if p.get("quoted_content"):
            quote_author = p.get("quoted_author") or "someone"
            quote_html = (
                f'<blockquote class="forum-quote">'
                f"<strong>{escape(quote_author)} wrote:</strong><br />"
                f"{escape(p['quoted_content'])}"
                f"</blockquote>"
            )

        sig_html = ""
        if sig:
            sig_html = f'<div class="forum-signature">{sig}</div>'

        edited = " · <em>(edited)</em>" if p.get("is_edited") else ""
        created = (
            p["created_at"].strftime("%Y-%m-%d %H:%M") if p.get("created_at") else ""
        )

        post_blocks.append(
            f'<div class="forum-post" id="post-{p["id"]}">'
            f'<div class="forum-post-meta">'
            f'<a href="../users/{p["author_username"]}/index.html">'
            f"<strong>{escape(p.get('author_display_name') or p['author_username'])}</strong></a>"
            f" · {created}{edited}"
            f"</div>"
            f"{quote_html}"
            f'<div class="forum-post-content">{rendered}</div>'
            f"{sig_html}"
            f"</div>"
        )

    content = "\n".join(post_blocks)

    # Thread-level custom CSS/HTML
    custom_css = thread.get("custom_css") or ""
    custom_html = thread.get("custom_html") or ""

    title = escape(thread["title"])
    author = escape(
        thread.get("author_display_name") or thread.get("author_username") or ""
    )
    created = (
        thread["created_at"].strftime("%Y-%m-%d %H:%M")
        if thread.get("created_at")
        else ""
    )

    pinned = " · 📌 pinned" if thread.get("is_pinned") else ""
    locked = " · 🔒 locked" if thread.get("is_locked") else ""

    header = (
        f'<h1>{title}</h1><p class="muted">by {author} · {created}{pinned}{locked}</p>'
    )

    # Rewrite media paths in forum content to relative paths
    content = _rewrite_all_media_paths(content, "..")
    custom_css = _rewrite_all_media_paths(custom_css, "..")
    custom_html = _rewrite_all_media_paths(custom_html, "..")

    tmpl = env.get_template("export_base.html")
    return tmpl.render(
        title=f"{title} — 4orm forum",
        content=f"{header}{content}",
        custom_css=custom_css,
        custom_html=custom_html,
        css_path="../style.css",
        site_url=site_url,
    )


def build_full_site_export_zip(
    conn: Connection,
    uploads_dir: str | Path,
    style_css_path: str | Path,
    site_url: str,
    templates_dir: str | Path,
) -> bytes:
    """Build a zip archive of the entire 4orm site. Returns raw bytes."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=False,
    )

    prefix = "4orm-export"
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # --- style.css ---
        css_path = Path(style_css_path)
        if css_path.exists():
            zf.write(css_path, f"{prefix}/style.css")

        # --- All users ---
        all_users = conn.execute(select(users).order_by(users.c.created_at)).fetchall()

        for urow in all_users:
            user = urow._mapping
            username = user["username"]

            # Per-user export into users/{username}/
            rendered_content = render_content(
                user["content"] or "", user["content_format"] or "html"
            )
            layout = user["layout"] or "default"

            # Fetch user's public pages
            user_pages = conn.execute(
                select(pages)
                .where(pages.c.user_id == user["id"], pages.c.is_public == True)  # noqa: E712
                .order_by(pages.c.created_at)
            ).fetchall()

            # Profile index
            if layout in ("default", ""):
                page_links = ""
                if user_pages:
                    items = "".join(
                        f'<li><a href="pages/{p._mapping["slug"]}.html">'
                        f"{escape(p._mapping['title'])}</a></li>"
                        for p in user_pages
                    )
                    page_links = f"<h2>pages</h2><ul>{items}</ul>"
                index_content = (
                    f'<section class="panel">'
                    f"<h1>{escape(user['display_name'])}</h1>"
                    f"{rendered_content}"
                    f"{page_links}"
                    f"</section>"
                )
            elif layout == "simple":
                index_content = rendered_content
            elif layout == "cssonly":
                index_content = ""
            else:
                index_content = rendered_content

            # Uploads prefix for users/{username}/index.html -> ../../style.css
            index_html = _render_export_page(
                env,
                escape(user["display_name"]),
                index_content,
                user["custom_css"] or "",
                user["custom_html"] or "",
                layout,
                "../../style.css",
                site_url,
                username,
            )
            zf.writestr(f"{prefix}/users/{username}/index.html", index_html)

            # Pages
            for p in user_pages:
                pm = p._mapping
                page_rendered = render_content(
                    pm["content"] or "", pm["content_format"] or "html"
                )
                page_layout = pm["layout"] or "default"

                if page_layout in ("default", ""):
                    page_content = (
                        f'<article class="panel content-html">'
                        f"<h1>{escape(pm['title'])}</h1>"
                        f'<p class="muted">by <a href="../index.html">'
                        f"{escape(user['display_name'])}</a></p>"
                        f"<hr />"
                        f"{page_rendered}"
                        f"</article>"
                    )
                elif page_layout == "simple":
                    page_content = page_rendered
                elif page_layout == "cssonly":
                    page_content = ""
                else:
                    page_content = page_rendered

                page_html = _render_export_page(
                    env,
                    escape(pm["title"]),
                    page_content,
                    user["custom_css"] or "",
                    user["custom_html"] or "",
                    page_layout,
                    "../../../style.css",
                    site_url,
                    username,
                )
                zf.writestr(
                    f"{prefix}/users/{username}/pages/{pm['slug']}.html",
                    page_html,
                )

            # Media files
            user_media = conn.execute(
                select(media.c.storage_path).where(media.c.user_id == user["id"])
            ).fetchall()
            uploads_path = Path(uploads_dir)
            for mrow in user_media:
                storage_path = mrow._mapping["storage_path"]
                file_path = uploads_path / storage_path
                filename = Path(storage_path).name
                if file_path.exists():
                    zf.write(
                        file_path,
                        f"{prefix}/users/{username}/uploads/{filename}",
                    )

        # --- Forum ---
        all_threads = conn.execute(
            select(
                forum_threads,
                users.c.username.label("author_username"),
                users.c.display_name.label("author_display_name"),
            )
            .select_from(
                forum_threads.join(users, forum_threads.c.author_id == users.c.id)
            )
            .order_by(forum_threads.c.created_at)
        ).fetchall()

        # Forum index page
        if all_threads:
            thread_rows = []
            for t in all_threads:
                tm = t._mapping
                pinned = "📌 " if tm.get("is_pinned") else ""
                locked = "🔒 " if tm.get("is_locked") else ""
                created = (
                    tm["created_at"].strftime("%Y-%m-%d")
                    if tm.get("created_at")
                    else ""
                )
                thread_rows.append(
                    f"<tr>"
                    f'<td>{pinned}{locked}<a href="{tm["id"]}.html">{escape(tm["title"])}</a></td>'
                    f'<td><a href="../users/{tm["author_username"]}/index.html">'
                    f"{escape(tm.get('author_display_name') or tm['author_username'])}</a></td>"
                    f"<td>{tm.get('reply_count', 0)}</td>"
                    f"<td>{created}</td>"
                    f"</tr>"
                )

            forum_index_content = (
                '<section class="panel">'
                "<h1>forum</h1>"
                '<table class="forum-table">'
                "<thead><tr>"
                "<th>thread</th><th>author</th><th>replies</th><th>date</th>"
                "</tr></thead>"
                f"<tbody>{''.join(thread_rows)}</tbody>"
                "</table>"
                "</section>"
            )

            tmpl = env.get_template("export_base.html")
            forum_index_html = tmpl.render(
                title="forum — 4orm",
                content=forum_index_content,
                custom_css="",
                custom_html="",
                css_path="../style.css",
                site_url=site_url,
            )
            zf.writestr(f"{prefix}/forum/index.html", forum_index_html)

        # Individual thread pages
        for t in all_threads:
            tm = t._mapping
            thread_posts = conn.execute(
                select(
                    forum_posts,
                    users.c.username.label("author_username"),
                    users.c.display_name.label("author_display_name"),
                    users.c.forum_signature.label("author_signature"),
                )
                .select_from(
                    forum_posts.join(users, forum_posts.c.author_id == users.c.id)
                )
                .where(forum_posts.c.thread_id == tm["id"])
                .order_by(forum_posts.c.created_at.asc())
            ).fetchall()

            posts = [p._mapping for p in thread_posts]
            thread_html = _render_forum_thread_html(env, tm, posts, site_url)
            zf.writestr(f"{prefix}/forum/{tm['id']}.html", thread_html)

    return buf.getvalue()
