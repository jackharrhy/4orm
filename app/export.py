import io
import re
import zipfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.rendering import build_raw_html, render_content
from app.schema import media, pages, users


def _rewrite_media_paths(content: str, username: str, prefix: str) -> str:
    """Rewrite /uploads/{username}/file.png to {prefix}/file.png."""
    return re.sub(
        rf"/uploads/{re.escape(username)}/",
        f"{prefix}/",
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
                    f"{p._mapping['title']}</a></li>"
                    for p in page_rows
                )
                page_links = f"<h2>pages</h2><ul>{items}</ul>"
            index_content = (
                f'<section class="panel">'
                f"<h1>{user['display_name']}</h1>"
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
            user["display_name"],
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
                    f"<h1>{pm['title']}</h1>"
                    f'<p class="muted">by <a href="../index.html">'
                    f"{user['display_name']}</a></p>"
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
                pm["title"],
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
