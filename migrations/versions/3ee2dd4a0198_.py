"""add body_type enum to cars"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3ee2dd4a0198'
down_revision: Union[str, None] = 'be938236e3a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# объявляем enum-тип отдельно, чтобы управлять .create()/.drop()
car_body_type = postgresql.ENUM(
    'SEDAN', 'SUV', 'CROSSOVER', 'COUPE', 'HATCHBACK',
    'CONVERTIBLE', 'WAGON', name='car_body_type'
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1) создаём тип (идемпотентно)
    car_body_type.create(bind, checkfirst=True)

    # 2) добавляем колонку; если в таблице уже есть строки, нужен временный default
    op.add_column(
        'cars',
        sa.Column(
            'body_type',
            car_body_type,
            nullable=False,
            server_default='SEDAN',  # временно, чтобы прошёл NOT NULL на существующих строках
        )
    )

    # 3) снимаем server_default, чтобы дальше писать явно
    op.alter_column('cars', 'body_type', server_default=None)


def downgrade() -> None:
    bind = op.get_bind()

    # 1) удаляем колонку
    op.drop_column('cars', 'body_type')

    # 2) удаляем сам тип (если больше нигде не используется)
    car_body_type.drop(bind, checkfirst=True)
