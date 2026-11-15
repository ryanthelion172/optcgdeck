"""add card_names (each card's name in other languages, Japanese for now) and
card_printings.language (which region's card list a printing came from)

Filled by scripts/import_cards.py, so run it after upgrading.

Revision ID: 0004_card_names
Revises: 0003_sets_printings_users
Create Date: 2026-11-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_card_names"
down_revision: Union[str, None] = "0003_sets_printings_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "card_names",
        sa.Column("card_id", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("card_id", "language"),
    )
    op.create_index("ix_card_names_name", "card_names", ["name"])
    op.add_column("card_printings", sa.Column("language", sa.String(length=10), server_default="en", nullable=False))


def downgrade() -> None:
    op.drop_column("card_printings", "language")
    op.drop_index("ix_card_names_name", table_name="card_names")
    op.drop_table("card_names")
