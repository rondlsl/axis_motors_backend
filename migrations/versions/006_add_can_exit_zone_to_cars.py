"""add can_exit_zone to cars

Revision ID: 006_add_can_exit_zone_to_cars
Revises: 005_add_notifications_disabled
Create Date: 2026-02-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_add_can_exit_zone_to_cars'
down_revision = '005_add_notifications_disabled'
branch_labels = None
depends_on = None


def upgrade():
    """
    Добавляет колонку can_exit_zone в таблицу cars.
    По умолчанию False (выезд за зону запрещён).
    """
    op.add_column('cars', sa.Column('can_exit_zone', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    """
    Удаляет колонку can_exit_zone из таблицы cars.
    """
    op.drop_column('cars', 'can_exit_zone')
