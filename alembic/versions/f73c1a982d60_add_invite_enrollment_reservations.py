"""Reserve member invites for central account enrollment.

Revision ID: f73c1a982d60
Revises: e92a6f3b1c40
"""

import sqlalchemy as sa

from alembic import op

revision = "f73c1a982d60"
down_revision = "e92a6f3b1c40"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_enrollments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "invite_id",
            sa.Integer(),
            sa.ForeignKey("invites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(255)),
        sa.Column("username", sa.String(32)),
        sa.Column("display_name", sa.String(80)),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")
        ),
        sa.Column("consumed_at", sa.Integer()),
    )
    op.create_index("ix_auth_enrollments_invite_id", "auth_enrollments", ["invite_id"])


def downgrade():
    op.drop_index("ix_auth_enrollments_invite_id", table_name="auth_enrollments")
    op.drop_table("auth_enrollments")
