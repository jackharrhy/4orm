"""add thread_watchers and watch_all_threads

Revision ID: 60bc32421300
Revises: 480d50092935
Create Date: 2026-04-09 17:11:03.608575

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "60bc32421300"
down_revision: str | Sequence[str] | None = "480d50092935"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "watch_all_threads", sa.Boolean(), nullable=False, server_default="0"
        ),
    )
    op.create_table(
        "thread_watchers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("forum_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "thread_id", name="uq_thread_watchers"),
    )
    # Auto-watch: make all existing thread authors watch their own threads
    op.execute(
        "INSERT INTO thread_watchers (user_id, thread_id) "
        "SELECT author_id, id FROM forum_threads"
    )


def downgrade() -> None:
    op.drop_table("thread_watchers")
    op.drop_column("users", "watch_all_threads")
