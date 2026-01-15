"""add accountant role

Revision ID: 003_add_accountant_role
Revises: 002_add_speed
Create Date: 2026-01-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003_add_accountant_role'
down_revision = '002_add_speed'
branch_labels = None
depends_on = None


def upgrade():
    """
    Добавляет новую роль ACCOUNTANT в enum userrole.
    PostgreSQL требует специального подхода для добавления значений в enum.
    """
    # Добавляем новое значение в enum userrole
    # ALTER TYPE не может выполняться в транзакции, поэтому используем специальный синтаксис
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'ACCOUNTANT'")
    
    # Также добавляем lowercase версию для совместимости
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'accountant'")


def downgrade():
    """
    Откат миграции.
    Внимание: PostgreSQL не поддерживает удаление значений из enum напрямую.
    Если нужно откатить, необходимо:
    1. Убедиться, что нет пользователей с ролью ACCOUNTANT
    2. Пересоздать тип enum без этого значения
    """
    # PostgreSQL не поддерживает удаление значений из enum
    # Это требует более сложной процедуры с пересозданием типа
    # Для безопасности оставляем pass
    pass

