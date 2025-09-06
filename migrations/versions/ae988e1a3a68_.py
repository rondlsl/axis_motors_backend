"""add MINIBUS to car_body_type by recreating enum"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ae988e1a3a68'
down_revision = "3ee2dd4a0198"
branch_labels = None
depends_on = None

OLD = ("SEDAN", "SUV", "CROSSOVER", "COUPE", "HATCHBACK", "CONVERTIBLE", "WAGON")
NEW = OLD + ("MINIBUS",)


def upgrade():
    # 1) создаём новый тип
    op.execute("CREATE TYPE car_body_type_new AS ENUM (" + ", ".join(f"'{v}'" for v in NEW) + ")")
    # 2) переводим колонку на новый тип
    op.execute("""
        ALTER TABLE cars
        ALTER COLUMN body_type TYPE car_body_type_new
        USING body_type::text::car_body_type_new
    """)
    # 3) удаляем старый тип и переименовываем новый
    op.execute("DROP TYPE car_body_type")
    op.execute("ALTER TYPE car_body_type_new RENAME TO car_body_type")


def downgrade():
    # Обратная операция: убираем MINIBUS
    op.execute("CREATE TYPE car_body_type_old AS ENUM (" + ", ".join(f"'{v}'" for v in OLD) + ")")

    # Если в данных есть MINIBUS, нужно решить, во что его конвертировать/удалить.
    # Простейший безопасный вариант: заменить на 'WAGON' перед сменой типа (или любой другой)
    op.execute("""
        UPDATE cars
        SET body_type = 'WAGON'
        WHERE body_type::text = 'MINIBUS'
    """)

    op.execute("""
        ALTER TABLE cars
        ALTER COLUMN body_type TYPE car_body_type_old
        USING body_type::text::car_body_type_old
    """)
    op.execute("DROP TYPE car_body_type")
    op.execute("ALTER TYPE car_body_type_old RENAME TO car_body_type")
