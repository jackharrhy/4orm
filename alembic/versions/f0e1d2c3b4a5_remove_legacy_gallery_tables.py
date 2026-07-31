"""remove legacy gallery tables

Revision ID: f0e1d2c3b4a5
Revises: de7c5007c2f0
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0e1d2c3b4a5"
down_revision: str | Sequence[str] | None = "de7c5007c2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("gallery_items", if_exists=True)
    op.drop_table("galleries", if_exists=True)

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    invite_fk = any(
        fk.get("constrained_columns") == ["invite_id"]
        and fk.get("referred_table") == "invites"
        for fk in inspector.get_foreign_keys("users")
    )
    if not invite_fk:
        with op.batch_alter_table("users") as batch_op:
            batch_op.create_foreign_key(
                "fk_users_invite_id",
                "invites",
                ["invite_id"],
                ["id"],
                ondelete="SET NULL",
            )

    device_constraint = any(
        set(constraint.get("column_names", [])) == {"user_id", "device_id"}
        for constraint in inspector.get_unique_constraints("push_subscriptions")
    )
    if not device_constraint:
        with op.batch_alter_table("push_subscriptions") as batch_op:
            batch_op.create_unique_constraint(
                "uq_push_user_device", ["user_id", "device_id"]
            )


def downgrade() -> None:
    pass
