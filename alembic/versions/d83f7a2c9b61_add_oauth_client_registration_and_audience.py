"""add oauth client registration and audience

Revision ID: d83f7a2c9b61
Revises: c52f4a10d871
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d83f7a2c9b61"
down_revision: str | Sequence[str] | None = "c52f4a10d871"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("oauth2_clients") as batch_op:
        batch_op.add_column(
            sa.Column(
                "registration_source",
                sa.String(length=24),
                server_default="declarative",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("allowed_resources", sa.Text(), server_default="", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_oauth2_clients_registration_source",
            "registration_source IN ('declarative', 'dynamic')",
        )

    with op.batch_alter_table("oauth2_authorization_codes") as batch_op:
        batch_op.add_column(
            sa.Column("resource", sa.Text(), server_default="", nullable=False)
        )

    with op.batch_alter_table("oauth2_tokens") as batch_op:
        batch_op.add_column(
            sa.Column("audience", sa.Text(), server_default="", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("oauth2_tokens") as batch_op:
        batch_op.drop_column("audience")

    with op.batch_alter_table("oauth2_authorization_codes") as batch_op:
        batch_op.drop_column("resource")

    with op.batch_alter_table("oauth2_clients") as batch_op:
        batch_op.drop_constraint("ck_oauth2_clients_registration_source", type_="check")
        batch_op.drop_column("allowed_resources")
        batch_op.drop_column("registration_source")
