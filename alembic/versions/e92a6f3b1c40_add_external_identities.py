"""Link central identity subjects to existing user records.

Revision ID: e92a6f3b1c40
Revises: d83f7a2c9b61
"""

import sqlalchemy as sa

from alembic import op

revision = "e92a6f3b1c40"
down_revision = "d83f7a2c9b61"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "external_identities",
        sa.Column("issuer", sa.String(255), primary_key=True),
        sa.Column("subject", sa.String(255), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_external_identities_user_id", "external_identities", ["user_id"]
    )


def downgrade():
    op.drop_index("ix_external_identities_user_id", table_name="external_identities")
    op.drop_table("external_identities")
