"""Keep post-commit enrollment delivery and companion grant receipts.

Revision ID: a72c80f30d91
Revises: f73c1a982d60
"""

import sqlalchemy as sa

from alembic import op

revision = "a72c80f30d91"
down_revision = "f73c1a982d60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "enrollment_completions",
        sa.Column(
            "request_id",
            sa.String(64),
            sa.ForeignKey("auth_enrollments.id"),
            primary_key=True,
        ),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("delivered_at", sa.Integer()),
        sa.Column("last_status", sa.Integer()),
    )
    op.create_table(
        "enrollment_grants",
        sa.Column(
            "request_id",
            sa.String(64),
            sa.ForeignKey("enrollment_completions.request_id"),
            primary_key=True,
        ),
        sa.Column("application_id", sa.String(16), primary_key=True),
        sa.Column("attempt_id", sa.String(128), nullable=False),
        sa.Column("grant_id", sa.String(255)),
        sa.Column("outcome", sa.String(16)),
        sa.CheckConstraint("application_id IN ('maps', 'burger')"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('created', 'preserved')"),
    )


def downgrade():
    op.drop_table("enrollment_grants")
    op.drop_table("enrollment_completions")
