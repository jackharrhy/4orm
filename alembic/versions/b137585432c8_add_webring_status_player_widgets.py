"""add webring status player widgets

Revision ID: b137585432c8
Revises: 33ec86d5b50e
Create Date: 2026-04-08 23:14:48.857238

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b137585432c8"
down_revision: str | Sequence[str] | None = "33ec86d5b50e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users", sa.Column("in_webring", sa.Boolean, nullable=False, server_default="0")
    )
    op.add_column(
        "users",
        sa.Column("status_emoji", sa.String(10), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("status_text", sa.String(140), nullable=False, server_default=""),
    )
    op.add_column("users", sa.Column("status_updated_at", sa.DateTime(timezone=True)))
    op.add_column(
        "users", sa.Column("status_css", sa.Text, nullable=False, server_default="")
    )
    op.add_column(
        "users", sa.Column("status_html", sa.Text, nullable=False, server_default="")
    )
    op.add_column(
        "users", sa.Column("player_css", sa.Text, nullable=False, server_default="")
    )
    op.add_column(
        "users", sa.Column("player_html", sa.Text, nullable=False, server_default="")
    )

    op.create_table(
        "playlist_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_id",
            sa.Integer,
            sa.ForeignKey("media.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("title", sa.String(200)),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("playlist_items")

    op.drop_column("users", "player_html")
    op.drop_column("users", "player_css")
    op.drop_column("users", "status_html")
    op.drop_column("users", "status_css")
    op.drop_column("users", "status_updated_at")
    op.drop_column("users", "status_text")
    op.drop_column("users", "status_emoji")
    op.drop_column("users", "in_webring")
