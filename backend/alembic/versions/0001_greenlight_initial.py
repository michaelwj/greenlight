"""Greenlight initial schema

Generated from the SQLAlchemy models so a fresh install always matches the
code. Future changes get their own incremental revisions.

Revision ID: 0001_greenlight_initial
Revises:
Create Date: 2026-08-14
"""

from alembic import op

from app.db.base import Base
from app.models import *  # noqa: F401,F403 — registers all tables on Base.metadata

revision = "0001_greenlight_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
