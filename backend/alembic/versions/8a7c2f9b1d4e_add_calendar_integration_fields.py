"""Add Google Calendar and Calendly integration fields to businesses table

Revision ID: 8a7c2f9b1d4e
Revises: 6f2a0d3e9c2b
Create Date: 2026-01-25 09:44:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a7c2f9b1d4e'
down_revision: Union[str, None] = '6f2a0d3e9c2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Google Calendar Integration columns
    op.add_column('businesses', sa.Column('google_calendar_id', sa.String(), nullable=True))
    op.add_column('businesses', sa.Column('google_refresh_token', sa.String(), nullable=True))
    op.add_column('businesses', sa.Column('google_token_expires_at', sa.DateTime(), nullable=True))
    op.add_column('businesses', sa.Column('google_calendar_timezone', sa.String(), nullable=False, server_default='Australia/Sydney'))
    
    # Calendly Integration columns
    op.add_column('businesses', sa.Column('calendly_api_key', sa.String(), nullable=True))
    op.add_column('businesses', sa.Column('calendly_username', sa.String(), nullable=True))
    op.add_column('businesses', sa.Column('calendly_calendar_url', sa.String(), nullable=True))
    
    # Calendar Sync Settings
    op.add_column('businesses', sa.Column('auto_sync_bookings', sa.Boolean(), nullable=False, server_default='true'))
    
    # Create indexes for calendar lookups
    op.create_index('idx_businesses_google_calendar_id', 'businesses', ['google_calendar_id'])
    op.create_index('idx_businesses_calendly_username', 'businesses', ['calendly_username'])


def downgrade() -> None:
    op.drop_index('idx_businesses_calendly_username', table_name='businesses')
    op.drop_index('idx_businesses_google_calendar_id', table_name='businesses')
    
    op.drop_column('businesses', 'auto_sync_bookings')
    op.drop_column('businesses', 'calendly_calendar_url')
    op.drop_column('businesses', 'calendly_username')
    op.drop_column('businesses', 'calendly_api_key')
    
    op.drop_column('businesses', 'google_calendar_timezone')
    op.drop_column('businesses', 'google_token_expires_at')
    op.drop_column('businesses', 'google_refresh_token')
    op.drop_column('businesses', 'google_calendar_id')
