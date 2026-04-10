import json

import bbcode
import bleach
import markdown


def render_content(source: str, content_format: str) -> str:
    """Render content source to HTML based on format."""
    if content_format == "markdown":
        return markdown.markdown(
            source,
            extensions=["fenced_code", "tables", "attr_list"],
        )
    return source


BLEACH_ALLOWED_TAGS = [
    "a",
    "abbr",
    "acronym",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
    "video",
    "audio",
    "iframe",
]
BLEACH_ALLOWED_ATTRS = {
    "a": ["href", "title", "target"],
    "img": ["src", "alt", "width", "height"],
    "video": ["src", "controls"],
    "iframe": ["src", "width", "height", "frameborder", "allowfullscreen"],
    "audio": ["src", "controls"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

_bbcode_parser = bbcode.Parser()
_bbcode_parser.add_simple_formatter(
    "img", '<img src="%(value)s" alt="" style="max-width:100%%" />', replace_links=False
)
_bbcode_parser.add_simple_formatter(
    "video",
    '<video controls src="%(value)s" style="max-width:100%%"></video>',
    replace_links=False,
)
_bbcode_parser.add_simple_formatter(
    "audio",
    '<audio controls src="%(value)s"></audio>',
    replace_links=False,
)


def render_forum_post(source: str, content_format: str) -> str:
    """Render a forum post to safe HTML."""
    if content_format == "bbcode":
        raw_html = _bbcode_parser.format(source)
        return bleach.clean(
            raw_html,
            tags=BLEACH_ALLOWED_TAGS,
            attributes=BLEACH_ALLOWED_ATTRS,
            strip=True,
        )
    # Markdown: render then sanitize
    raw_html = markdown.markdown(
        source, extensions=["fenced_code", "tables", "attr_list"]
    )
    return bleach.clean(
        raw_html,
        tags=BLEACH_ALLOWED_TAGS,
        attributes=BLEACH_ALLOWED_ATTRS,
        strip=True,
    )


def render_signature(source: str) -> str:
    """Render a forum signature (always BBCode, sanitized)."""
    if not source:
        return ""
    raw_html = _bbcode_parser.format(source)
    return bleach.clean(
        raw_html,
        tags=BLEACH_ALLOWED_TAGS,
        attributes=BLEACH_ALLOWED_ATTRS,
        strip=True,
    )


def _inject_into_head(html: str, snippet: str) -> str:
    """Inject a snippet right after <head> (or after <html> if no <head>)."""
    for tag in ("<head>", "<HEAD>", "<head >"):
        pos = html.find(tag)
        if pos != -1:
            insert_at = pos + len(tag)
            return html[:insert_at] + "\n" + snippet + "\n" + html[insert_at:]
    # No <head> tag -- try after <html>
    for tag in ("<html>", "<HTML>", "<html "):
        pos = html.find(tag)
        if pos != -1:
            end = html.find(">", pos) + 1
            return html[:end] + "\n" + snippet + "\n" + html[end:]
    # No structure at all -- prepend
    return snippet + "\n" + html


def build_raw_html(
    rendered_content: str,
    custom_css: str = "",
    custom_html: str = "",
    data: dict | None = None,
) -> str:
    """Build a complete raw HTML page from user content."""
    html = rendered_content

    # Inject __4ORM data into <head> so it's available before user scripts run
    if data:
        json_data = json.dumps(data, default=str)
        html = _inject_into_head(html, f"<script>window.__4ORM = {json_data};</script>")

    # Append custom assets at the end (CSS/HTML may depend on user DOM)
    if custom_css:
        html += f"\n<style>{custom_css}</style>"
    if custom_html:
        html += f"\n{custom_html}"

    return html
