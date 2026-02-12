"""add daily_user_stats for pre-aggregated registration analytics

Revision ID: 010_add_daily_user_stats
Revises: 009_add_bonus_promo_codes
Create Date: 2026-02

"""
from alembic import op
import sqlalchemy as sa


revision = "010_add_daily_user_stats"
down_revision = "009_add_bonus_promo_codes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_user_stats",
        sa.Column("date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("registered_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # PK на date даёт уникальный индекс — его достаточно для range-запросов (date >= ? AND date <= ?)


def downgrade():
    op.drop_table("daily_user_stats")
