"""add has_accepted_trust to users

Revision ID: 518358acc870
Revises: b137585432c8
Create Date: 2026-04-09 11:05:19.016005

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "518358acc870"
down_revision: str | Sequence[str] | None = "b137585432c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "has_accepted_trust",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # All existing users have implicitly accepted
    op.execute("UPDATE users SET has_accepted_trust = 1")


def downgrade() -> None:
    op.drop_column("users", "has_accepted_trust")
