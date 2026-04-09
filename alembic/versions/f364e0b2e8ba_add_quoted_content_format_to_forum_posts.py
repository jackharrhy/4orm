"""add quoted_content_format to forum_posts

Revision ID: f364e0b2e8ba
Revises: 518358acc870
Create Date: 2026-04-09 12:46:06.453004

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f364e0b2e8ba"
down_revision: Union[str, Sequence[str], None] = "518358acc870"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("forum_posts", sa.Column("quoted_content_format", sa.String(20)))
    # Backfill: look up the content_format of the quoted post
    op.execute(
        "UPDATE forum_posts SET quoted_content_format = ("
        "  SELECT fp2.content_format FROM forum_posts fp2"
        "  WHERE fp2.id = forum_posts.quoted_post_id"
        ") WHERE forum_posts.quoted_post_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("forum_posts", "quoted_content_format")
