"""add machine oauth principals

Revision ID: a41c9e7d2b10
Revises: 8f7a1c2d3e4f
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a41c9e7d2b10"
down_revision: str | Sequence[str] | None = "8f7a1c2d3e4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("oauth2_clients") as batch_op:
        batch_op.alter_column(
            "client_secret", new_column_name="client_secret_hash", type_=sa.Text()
        )
        batch_op.add_column(
            sa.Column(
                "previous_client_secret_hash",
                sa.Text(),
                server_default="",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "principal_type",
                sa.String(length=20),
                server_default="user",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "subject", sa.String(length=120), server_default="", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("is_enabled", sa.Boolean(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "can_introspect", sa.Boolean(), server_default="0", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column(
                "access_token_lifetime",
                sa.Integer(),
                server_default="3600",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("secret_rotated_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )

    # Existing configured clients are public and have empty secrets. Refuse to
    # preserve any unexpected plaintext credential in the renamed column.
    op.execute(
        sa.text(
            "UPDATE oauth2_clients SET client_secret_hash = '' "
            "WHERE client_secret_hash != ''"
        )
    )

    with op.batch_alter_table("oauth2_tokens") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(
            sa.Column(
                "principal_type",
                sa.String(length=20),
                server_default="user",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "subject", sa.String(length=120), server_default="", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column(
                "grant_type",
                sa.String(length=40),
                server_default="authorization_code",
                nullable=False,
            )
        )

    op.execute(sa.text("UPDATE oauth2_tokens SET subject = CAST(user_id AS TEXT)"))

    op.create_table(
        "oauth2_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("client_id", sa.String(length=48)),
        sa.Column("token_id", sa.Integer()),
        sa.Column("actor_user_id", sa.Integer()),
        sa.Column("success", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("detail", sa.Text(), server_default="", nullable=False),
        sa.Column("source_ip", sa.String(length=64), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("oauth2_audit_events")

    with op.batch_alter_table("oauth2_tokens") as batch_op:
        batch_op.drop_column("grant_type")
        batch_op.drop_column("subject")
        batch_op.drop_column("principal_type")
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("oauth2_clients") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("disabled_at")
        batch_op.drop_column("secret_rotated_at")
        batch_op.drop_column("access_token_lifetime")
        batch_op.drop_column("can_introspect")
        batch_op.drop_column("is_enabled")
        batch_op.drop_column("subject")
        batch_op.drop_column("principal_type")
        batch_op.drop_column("previous_client_secret_hash")
        batch_op.alter_column(
            "client_secret_hash",
            new_column_name="client_secret",
            type_=sa.String(length=120),
        )
