import json

import markdown


def render_content(source: str, content_format: str) -> str:
    """Render content source to HTML based on format."""
    if content_format == "markdown":
        return markdown.markdown(
            source,
            extensions=["fenced_code", "tables", "attr_list"],
        )
    return source


def build_raw_html(
    rendered_content: str,
    custom_css: str = "",
    custom_html: str = "",
    data: dict | None = None,
) -> str:
    """Build a complete raw HTML page from user content."""
    parts = [rendered_content]
    if custom_css:
        parts.append(f"<style>{custom_css}</style>")
    if custom_html:
        parts.append(custom_html)
    if data:
        json_data = json.dumps(data, default=str)
        parts.append(f"<script>window.__4ORM = {json_data};</script>")
    return "\n".join(parts)
