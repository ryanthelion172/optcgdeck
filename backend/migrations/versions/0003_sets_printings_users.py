"""add sets, card printings and users; decks get an owner

- `sets` replaces the free-text `cards.pack` column (cards point at it with `set_id`).
- `card_printings` holds every printing of a card (base art and alternate
  arts) with its image. It replaces `cards.image` and `cards.variants`; the
  existing images and alternate arts are moved over.
- `users` holds accounts, and `decks.owner_id` points at the deck's owner.
  Decks made without an account keep their `owner_hash`, which is now optional.

Sets can't be filled from the old `pack` text (it has no source ids), so run
scripts/import_cards.py after upgrading to fill them in.

Revision ID: 0003_sets_printings_users
Revises: 0002_cards
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_sets_printings_users"
down_revision: Union[str, None] = "0002_cards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sets",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("cards", sa.Column("set_id", sa.String(length=20), nullable=True))
    op.create_foreign_key("cards_set_id_fkey", "cards", "sets", ["set_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_cards_set_id", "cards", ["set_id"])

    op.create_table(
        "card_printings",
        sa.Column("id", sa.String(length=30), nullable=False),
        sa.Column("card_id", sa.String(length=20), nullable=False),
        sa.Column("is_base", sa.Boolean(), nullable=False),
        sa.Column("set_id", sa.String(length=20), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["set_id"], ["sets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_printings_card_id", "card_printings", ["card_id"])
    op.create_index(
        "uq_card_printings_one_base", "card_printings", ["card_id"], unique=True, postgresql_where=sa.text("is_base")
    )

    # Move the base images and alternate arts over.
    op.execute(
        """
        INSERT INTO card_printings (id, card_id, is_base, image_url)
        SELECT id, id, true, image FROM cards
        """
    )
    op.execute(
        """
        INSERT INTO card_printings (id, card_id, is_base, image_url)
        SELECT v->>'id', c.id, false, v->>'image'
        FROM cards c, jsonb_array_elements(c.variants) AS v
        WHERE v->>'id' IS NOT NULL
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.drop_column("cards", "image")
    op.drop_column("cards", "variants")
    op.drop_column("cards", "pack")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.add_column("decks", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("decks_owner_id_fkey", "decks", "users", ["owner_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_decks_owner_id", "decks", ["owner_id"])
    op.alter_column("decks", "owner_hash", existing_type=sa.String(length=64), nullable=True)
    op.create_check_constraint("decks_have_an_owner", "decks", "owner_id IS NOT NULL OR owner_hash IS NOT NULL")


def downgrade() -> None:
    # Decks owned only by an account have no owner key to fall back to, so they go.
    op.execute("DELETE FROM decks WHERE owner_hash IS NULL")
    op.drop_constraint("decks_have_an_owner", "decks", type_="check")
    op.alter_column("decks", "owner_hash", existing_type=sa.String(length=64), nullable=False)
    op.drop_index("ix_decks_owner_id", table_name="decks")
    op.drop_constraint("decks_owner_id_fkey", "decks", type_="foreignkey")
    op.drop_column("decks", "owner_id")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")

    op.add_column("cards", sa.Column("pack", sa.String(length=100), nullable=True))
    op.add_column(
        "cards",
        sa.Column("variants", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column("cards", sa.Column("image", sa.Text(), nullable=True))
    op.alter_column("cards", "variants", server_default=None)
    op.execute("UPDATE cards c SET pack = s.code FROM sets s WHERE s.id = c.set_id")
    op.execute("UPDATE cards c SET image = p.image_url FROM card_printings p WHERE p.card_id = c.id AND p.is_base")
    op.execute(
        """
        UPDATE cards c SET variants = v.list
        FROM (
            SELECT card_id, jsonb_agg(jsonb_build_object('id', id, 'image', image_url) ORDER BY id) AS list
            FROM card_printings WHERE NOT is_base GROUP BY card_id
        ) v
        WHERE v.card_id = c.id
        """
    )
    op.drop_index("uq_card_printings_one_base", table_name="card_printings")
    op.drop_index("ix_card_printings_card_id", table_name="card_printings")
    op.drop_table("card_printings")
    op.drop_index("ix_cards_set_id", table_name="cards")
    op.drop_constraint("cards_set_id_fkey", "cards", type_="foreignkey")
    op.drop_column("cards", "set_id")
    op.drop_table("sets")
