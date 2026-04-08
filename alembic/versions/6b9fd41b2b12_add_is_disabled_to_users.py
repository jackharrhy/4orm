"""add is_disabled to users

Revision ID: 6b9fd41b2b12
Revises: 2e486ad14546
Create Date: 2026-04-08 02:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b9fd41b2b12"
down_revision = "2e486ad14546"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("users", "is_disabled")
