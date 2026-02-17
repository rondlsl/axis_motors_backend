"""add user email reputation fields (email_status, bounce_count, last_bounce_at)

Revision ID: 011_add_email_reputation_fields
Revises: 010_add_daily_user_stats
Create Date: 2026-02

"""
from alembic import op
import sqlalchemy as sa


revision = "011_add_email_reputation_fields"
down_revision = "010_add_daily_user_stats"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_status", sa.String(20), nullable=True, server_default="pending"))
    op.add_column("users", sa.Column("bounce_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("last_bounce_at", sa.DateTime(), nullable=True))
    # Already verified emails are safe to send to
    op.execute("UPDATE users SET email_status = 'verified' WHERE is_verified_email = true AND email_status = 'pending'")


def downgrade():
    op.drop_column("users", "last_bounce_at")
    op.drop_column("users", "bounce_count")
    op.drop_column("users", "email_status")
