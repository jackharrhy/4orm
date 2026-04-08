"""add counter_css and counter_html to users

Revision ID: 33ec86d5b50e
Revises: 6e3a616daaea
Create Date: 2026-04-08 15:37:04.063499

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "33ec86d5b50e"
down_revision: Union[str, Sequence[str], None] = "6e3a616daaea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("counter_css", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "users", sa.Column("counter_html", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("users", "counter_html")
    op.drop_column("users", "counter_css")
