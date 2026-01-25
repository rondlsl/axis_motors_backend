"""add open_fee to cars

Revision ID: 004_add_open_fee
Revises: 003_add_accountant_role
Create Date: 2026-01-25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_add_open_fee'
down_revision = '003_add_accountant_role'
branch_labels = None
depends_on = None


def upgrade():
    """
    Добавляет колонку open_fee в таблицу cars.
    По умолчанию 4000 для всех машин.
    Затем обновляет специфичные машины с индивидуальными значениями.
    """
    # Шаг 1: Добавляем колонку open_fee с дефолтным значением 4000
    op.add_column('cars', sa.Column('open_fee', sa.Integer(), nullable=False, server_default='4000'))
    
    # Шаг 2: Обновляем машины с car_class = 2 (6000₸)
    op.execute("""
        UPDATE cars 
        SET open_fee = 6000 
        WHERE car_class = 2
    """)
    
    # Шаг 3: Обновляем машины с car_class = 3 (8000₸)
    op.execute("""
        UPDATE cars 
        SET open_fee = 8000 
        WHERE car_class = 3
    """)
    
    # Шаг 4: Обновляем специфичные машины по gps_imei
    # G63, Maserati и Mercedes W222 - 8000₸
    op.execute("""
        UPDATE cars 
        SET open_fee = 8000 
        WHERE gps_imei IN ('860803068155890', '860803068139613', '860803068133152')
    """)
    
    # Range Rover Sport Supercharged - 6000₸
    op.execute("""
        UPDATE cars 
        SET open_fee = 6000 
        WHERE gps_imei = '860803068151105'
    """)
    
    # Li L7 Ultra - 6000₸
    op.execute("""
        UPDATE cars 
        SET open_fee = 6000 
        WHERE gps_imei = '860803068133657'
    """)
    
    # BMW 530i (G30) - 6000₸
    op.execute("""
        UPDATE cars 
        SET open_fee = 6000 
        WHERE gps_imei = '860803068133343'
    """)


def downgrade():
    """
    Удаляет колонку open_fee из таблицы cars.
    """
    op.drop_column('cars', 'open_fee')
