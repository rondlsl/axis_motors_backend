"""Add car comments and status history tables

Revision ID: add_car_comments_tables
Revises: 3c445a622bb0
Create Date: 2024-01-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_car_comments_tables'
down_revision = '3c445a622bb0'
branch_labels = None
depends_on = None


def upgrade():
    # Создаем таблицу car_comments
    op.create_table('car_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('car_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['car_id'], ['cars.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_car_comments_id'), 'car_comments', ['id'], unique=False)

    # Создаем таблицу car_status_history
    op.create_table('car_status_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('car_id', sa.Integer(), nullable=False),
        sa.Column('old_status', sa.String(), nullable=True),
        sa.Column('new_status', sa.String(), nullable=False),
        sa.Column('changed_by_id', sa.Integer(), nullable=False),
        sa.Column('change_reason', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['car_id'], ['cars.id'], ),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_car_status_history_id'), 'car_status_history', ['id'], unique=False)


def downgrade():
    # Удаляем таблицы в обратном порядке
    op.drop_index(op.f('ix_car_status_history_id'), table_name='car_status_history')
    op.drop_table('car_status_history')
    op.drop_index(op.f('ix_car_comments_id'), table_name='car_comments')
    op.drop_table('car_comments')
