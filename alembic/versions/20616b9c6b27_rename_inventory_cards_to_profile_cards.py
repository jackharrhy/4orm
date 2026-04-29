"""rename inventory_cards to profile_cards

Revision ID: 20616b9c6b27
Revises: b10fe17d4124
Create Date: 2026-04-06 13:55:16.745371

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20616b9c6b27"
down_revision: str | Sequence[str] | None = "b10fe17d4124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("inventory_cards", "profile_cards")


def downgrade() -> None:
    op.rename_table("profile_cards", "inventory_cards")
