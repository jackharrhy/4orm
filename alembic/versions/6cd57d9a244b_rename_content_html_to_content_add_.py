"""rename content_html to content add content_format

Revision ID: 6cd57d9a244b
Revises: 7a9fcee16766
Create Date: 2026-04-06 15:39:53.655335

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6cd57d9a244b"
down_revision: str | Sequence[str] | None = "7a9fcee16766"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pages: rename content_html -> content, add content_format
    op.alter_column("pages", "content_html", new_column_name="content")
    op.add_column(
        "pages",
        sa.Column(
            "content_format", sa.String(20), nullable=False, server_default="html"
        ),
    )

    # profile_cards: add content_format
    op.add_column(
        "profile_cards",
        sa.Column(
            "content_format", sa.String(20), nullable=False, server_default="html"
        ),
    )


def downgrade() -> None:
    op.drop_column("profile_cards", "content_format")
    op.drop_column("pages", "content_format")
    op.alter_column("pages", "content", new_column_name="content_html")
