"""add site banner settings

Revision ID: 8f7a1c2d3e4f
Revises: f0e1d2c3b4a5
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f7a1c2d3e4f"
down_revision: str | Sequence[str] | None = "f0e1d2c3b4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("banner_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("banner_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("banner_css", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("site_settings")
