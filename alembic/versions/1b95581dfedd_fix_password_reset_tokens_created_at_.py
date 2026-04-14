"""fix password_reset_tokens created_at default

Revision ID: 1b95581dfedd
Revises: 9a1d2c44e7f1
Create Date: 2026-04-14 14:15:40.897740

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1b95581dfedd"
down_revision: Union[str, Sequence[str], None] = "9a1d2c44e7f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("password_reset_tokens") as batch_op:
        batch_op.alter_column(
            "created_at",
            server_default=sa.func.now(),
        )


def downgrade() -> None:
    with op.batch_alter_table("password_reset_tokens") as batch_op:
        batch_op.alter_column(
            "created_at",
            server_default=None,
        )
