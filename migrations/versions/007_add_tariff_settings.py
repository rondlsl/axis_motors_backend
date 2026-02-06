"""add tariff_settings table

Revision ID: 007_add_tariff_settings
Revises: 006_add_can_exit_zone_to_cars
Create Date: 2026

"""
from alembic import op
import sqlalchemy as sa


revision = "007_add_tariff_settings"
down_revision = "006_add_can_exit_zone_to_cars"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tariff_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("minutes_tariff_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("hourly_tariff_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("hourly_min_hours", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO tariff_settings (id, minutes_tariff_enabled, hourly_tariff_enabled, hourly_min_hours) "
        "VALUES (1, true, true, 1)"
    )


def downgrade():
    op.drop_table("tariff_settings")
