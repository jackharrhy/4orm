"""add custom_html to users

Revision ID: 7a9fcee16766
Revises: 4c3cc046a8dc
Create Date: 2026-04-06 15:27:39.417848

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a9fcee16766"
down_revision: str | Sequence[str] | None = "4c3cc046a8dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("custom_html", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("users", "custom_html")
