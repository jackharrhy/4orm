"""add layout column to users and pages

Revision ID: 12d656020cc9
Revises: 3aacbfd63cd0
Create Date: 2026-04-07 14:22:56.712172

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "12d656020cc9"
down_revision: Union[str, Sequence[str], None] = "3aacbfd63cd0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("layout", sa.String(20), nullable=False, server_default="default"),
    )
    op.add_column(
        "pages",
        sa.Column("layout", sa.String(20), nullable=False, server_default="default"),
    )


def downgrade() -> None:
    op.drop_column("pages", "layout")
    op.drop_column("users", "layout")
