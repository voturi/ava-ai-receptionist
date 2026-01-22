"""Add policies and faqs tables

Revision ID: 6f2a0d3e9c2b
Revises: 3334ac86870b
Create Date: 2026-01-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f2a0d3e9c2b'
down_revision: Union[str, None] = '3334ac86870b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'idx_bookings_business_phone_datetime',
        'bookings',
        ['business_id', 'customer_phone', 'booking_datetime']
    )
    op.create_table(
        'policies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('business_id', sa.UUID(), nullable=False),
        sa.Column('topic', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_policies_business_id', 'policies', ['business_id'])
    op.create_index('idx_policies_business_topic', 'policies', ['business_id', 'topic'])

    op.create_table(
        'faqs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('business_id', sa.UUID(), nullable=False),
        sa.Column('topic', sa.String(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_faqs_business_id', 'faqs', ['business_id'])
    op.create_index('idx_faqs_business_topic', 'faqs', ['business_id', 'topic'])


def downgrade() -> None:
    op.drop_index('idx_bookings_business_phone_datetime', table_name='bookings')
    op.drop_index('idx_faqs_business_topic', table_name='faqs')
    op.drop_index('idx_faqs_business_id', table_name='faqs')
    op.drop_table('faqs')

    op.drop_index('idx_policies_business_topic', table_name='policies')
    op.drop_index('idx_policies_business_id', table_name='policies')
    op.drop_table('policies')
