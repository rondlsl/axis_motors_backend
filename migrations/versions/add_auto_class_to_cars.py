"""add auto_class to cars

Revision ID: add_auto_class_to_cars
Revises: 
Create Date: 2025-09-17 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_auto_class_to_cars'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создать enum тип
    car_auto_class_enum = postgresql.ENUM('A', 'B', 'C', name='car_auto_class')
    car_auto_class_enum.create(op.get_bind())
    
    # Добавить колонку
    op.add_column('cars', sa.Column('auto_class', car_auto_class_enum, nullable=False, server_default='A'))


def downgrade() -> None:
    # Удалить колонку
    op.drop_column('cars', 'auto_class')
    
    # Удалить enum тип
    car_auto_class_enum = postgresql.ENUM('A', 'B', 'C', name='car_auto_class')
    car_auto_class_enum.drop(op.get_bind())
