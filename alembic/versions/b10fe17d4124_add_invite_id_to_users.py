"""add invite_id to users

Revision ID: b10fe17d4124
Revises:
Create Date: 2026-04-06 12:15:30.949859

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b10fe17d4124"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("invite_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_invite_id",
        "users",
        "invites",
        ["invite_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Backfill: prod has only used single-use invites (1:1 invite-to-user).
    op.execute(
        "UPDATE users SET invite_id = ("
        "  SELECT invites.id FROM invites WHERE invites.used_by_user_id = users.id"
        ")"
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_invite_id", "users", type_="foreignkey")
    op.drop_column("users", "invite_id")
