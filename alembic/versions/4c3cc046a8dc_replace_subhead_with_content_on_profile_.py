"""replace subhead with content on profile_cards

Revision ID: 4c3cc046a8dc
Revises: 20616b9c6b27
Create Date: 2026-04-06 15:04:04.930133

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4c3cc046a8dc"
down_revision: Union[str, Sequence[str], None] = "20616b9c6b27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profile_cards",
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
    )
    op.execute("UPDATE profile_cards SET content = subhead WHERE subhead != ''")
    op.drop_column("profile_cards", "subhead")


def downgrade() -> None:
    op.add_column(
        "profile_cards",
        sa.Column("subhead", sa.String(200), nullable=False, server_default=""),
    )
    op.execute("UPDATE profile_cards SET subhead = content WHERE content != ''")
    op.drop_column("profile_cards", "content")
