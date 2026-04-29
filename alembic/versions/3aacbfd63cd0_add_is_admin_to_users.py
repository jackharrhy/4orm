"""add is_admin to users

Revision ID: 3aacbfd63cd0
Revises: eb6632a6d559
Create Date: 2026-04-06 16:33:52.307470

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3aacbfd63cd0"
down_revision: str | Sequence[str] | None = "eb6632a6d559"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
