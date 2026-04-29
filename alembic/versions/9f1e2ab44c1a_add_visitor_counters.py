"""add visitor counters

Revision ID: 9f1e2ab44c1a
Revises: 6b9fd41b2b12
Create Date: 2026-04-08 02:20:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "9f1e2ab44c1a"
down_revision = "6b9fd41b2b12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visitor_counters",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "total_views", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("visitor_counters")
