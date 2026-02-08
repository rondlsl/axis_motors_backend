"""add bonus promo codes tables

Revision ID: 009_add_bonus_promo_codes
Revises: 008_add_tariff_to_cars
Create Date: 2026

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "009_add_bonus_promo_codes"
down_revision = "008_add_tariff_to_cars"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bonus_promo_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("bonus_amount", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("bonus_amount > 0", name="ck_bonus_promo_amount_positive"),
        sa.CheckConstraint("valid_to > valid_from", name="ck_bonus_promo_dates_order"),
    )

    op.create_table(
        "bonus_promo_usages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("promo_code_id", UUID(as_uuid=True), sa.ForeignKey("bonus_promo_codes.id"), nullable=False, index=True),
        sa.Column("used_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "promo_code_id", name="uq_bonus_promo_user_code"),
    )


def downgrade():
    op.drop_table("bonus_promo_usages")
    op.drop_table("bonus_promo_codes")
