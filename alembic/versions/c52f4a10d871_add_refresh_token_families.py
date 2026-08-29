"""add refresh token families

Revision ID: c52f4a10d871
Revises: a41c9e7d2b10
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c52f4a10d871"
down_revision: str | Sequence[str] | None = "a41c9e7d2b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("oauth2_tokens") as batch_op:
        batch_op.add_column(sa.Column("refresh_family_id", sa.String(length=64)))
        batch_op.add_column(
            sa.Column(
                "refresh_family_compromised",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.create_index(
            "ix_oauth2_tokens_refresh_family_id", ["refresh_family_id"]
        )

    op.execute(
        sa.text(
            "UPDATE oauth2_tokens "
            "SET refresh_family_id = lower(hex(randomblob(16))) "
            "WHERE refresh_token IS NOT NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("oauth2_tokens") as batch_op:
        batch_op.drop_index("ix_oauth2_tokens_refresh_family_id")
        batch_op.drop_column("refresh_family_compromised")
        batch_op.drop_column("refresh_family_id")
