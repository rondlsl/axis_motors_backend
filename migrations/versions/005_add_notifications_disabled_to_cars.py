"""add notifications_disabled to cars

Revision ID: 005_add_notifications_disabled
Revises: 004_add_open_fee
Create Date: 2026-02-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_add_notifications_disabled'
down_revision = '004_add_open_fee'
branch_labels = None
depends_on = None


def upgrade():
    """
    Добавляет колонку notifications_disabled в таблицу cars.
    По умолчанию False (уведомления включены).
    """
    op.add_column('cars', sa.Column('notifications_disabled', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    """
    Удаляет колонку notifications_disabled из таблицы cars.
    """
    op.drop_column('cars', 'notifications_disabled')
