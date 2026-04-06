import markdown


def render_content(source: str, content_format: str) -> str:
    """Render content source to HTML based on format."""
    if content_format == "markdown":
        return markdown.markdown(
            source,
            extensions=["fenced_code", "tables", "attr_list"],
        )
    return source
