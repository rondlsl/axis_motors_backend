"""add speed to cars

Revision ID: 002_add_speed
Revises: 001_initial_migration
Create Date: 2024-12-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_add_speed'
down_revision = '001_initial_migration'
branch_labels = None
depends_on = None


def upgrade():
    # Add speed column to cars table
    op.add_column('cars', sa.Column('speed', sa.Float(), nullable=True))


def downgrade():
    # Remove speed column from cars table
    op.drop_column('cars', 'speed')

