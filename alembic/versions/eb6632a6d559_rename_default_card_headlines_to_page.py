"""rename default card headlines to page

Revision ID: eb6632a6d559
Revises: 10767a340004
Create Date: 2026-04-06 16:20:20.846487

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "eb6632a6d559"
down_revision: Union[str, Sequence[str], None] = "10767a340004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE profile_cards SET headline = REPLACE(headline, '''s card', '''s page')"
        " WHERE headline LIKE '%''s card'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE profile_cards SET headline = REPLACE(headline, '''s page', '''s card')"
        " WHERE headline LIKE '%''s page'"
    )
