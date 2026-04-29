"""add device_id and device_name to push_subscriptions

Revision ID: fc10625ecaf2
Revises: 60bc32421300
Create Date: 2026-04-11 13:22:33.062518

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fc10625ecaf2"
down_revision: str | Sequence[str] | None = "60bc32421300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Wipe all stale/duplicate subscriptions -- devices will re-subscribe
    op.execute("DELETE FROM push_subscriptions")
    op.add_column(
        "push_subscriptions",
        sa.Column("device_id", sa.String(64), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "push_subscriptions",
        sa.Column("device_name", sa.String(100), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("push_subscriptions", "device_name")
    op.drop_column("push_subscriptions", "device_id")
