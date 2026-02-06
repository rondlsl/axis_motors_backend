"""add tariff fields to cars

Revision ID: 008_add_tariff_to_cars
Revises: 007_add_tariff_settings
Create Date: 2026

"""
from alembic import op
import sqlalchemy as sa


revision = "008_add_tariff_to_cars"
down_revision = "007_add_tariff_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cars", sa.Column("minutes_tariff_enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("cars", sa.Column("hourly_tariff_enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("cars", sa.Column("hourly_min_hours", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    op.drop_column("cars", "hourly_min_hours")
    op.drop_column("cars", "hourly_tariff_enabled")
    op.drop_column("cars", "minutes_tariff_enabled")
