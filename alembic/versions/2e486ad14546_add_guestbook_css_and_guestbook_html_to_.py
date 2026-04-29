"""add guestbook_css and guestbook_html to users

Revision ID: 2e486ad14546
Revises: 554fa9bb8f44
Create Date: 2026-04-07 18:40:09.091627

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2e486ad14546"
down_revision: str | Sequence[str] | None = "554fa9bb8f44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("guestbook_css", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("guestbook_html", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("users", "guestbook_html")
    op.drop_column("users", "guestbook_css")
