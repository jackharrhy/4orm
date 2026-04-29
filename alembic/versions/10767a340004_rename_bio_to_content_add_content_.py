"""rename bio to content add content_format on users

Revision ID: 10767a340004
Revises: 6cd57d9a244b
Create Date: 2026-04-06 16:07:53.136637

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "10767a340004"
down_revision: str | Sequence[str] | None = "6cd57d9a244b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "bio", new_column_name="content")
    op.add_column(
        "users",
        sa.Column(
            "content_format", sa.String(20), nullable=False, server_default="html"
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "content_format")
    op.alter_column("users", "content", new_column_name="bio")
