"""add cards table and point decks at it

Decks saved before this change are removed (they were only test data), so the
new foreign keys can be added cleanly.

Revision ID: 0002_cards
Revises: b99e327a1cc5
Create Date: 2026-10-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_cards"
down_revision: Union[str, None] = "b99e327a1cc5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cards",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("colors", postgresql.JSONB(), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=True),
        sa.Column("life", sa.Integer(), nullable=True),
        sa.Column("power", sa.Integer(), nullable=True),
        sa.Column("counter", sa.Integer(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("types", postgresql.JSONB(), nullable=False),
        sa.Column("effect", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("rarity", sa.String(length=20), nullable=True),
        sa.Column("set_code", sa.String(length=10), nullable=False),
        sa.Column("pack", sa.String(length=100), nullable=True),
        sa.Column("block", sa.Integer(), nullable=True),
        sa.Column("image", sa.Text(), nullable=True),
        sa.Column("variants", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cards_set_code"), "cards", ["set_code"], unique=False)

    op.execute("DELETE FROM decks")  # deck_cards rows go with them (ON DELETE CASCADE)
    op.create_foreign_key(
        "deck_cards_card_id_fkey", "deck_cards", "cards", ["card_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_deck_cards_card_id", "deck_cards", ["card_id"], unique=False)
    op.create_foreign_key(
        "decks_leader_id_fkey", "decks", "cards", ["leader_id"], ["id"], ondelete="RESTRICT"
    )


def downgrade() -> None:
    op.drop_constraint("decks_leader_id_fkey", "decks", type_="foreignkey")
    op.drop_index("ix_deck_cards_card_id", table_name="deck_cards")
    op.drop_constraint("deck_cards_card_id_fkey", "deck_cards", type_="foreignkey")
    op.drop_index(op.f("ix_cards_set_code"), table_name="cards")
    op.drop_table("cards")
