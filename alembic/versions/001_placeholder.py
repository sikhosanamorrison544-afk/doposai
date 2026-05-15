"""Placeholder baseline (schema created via SQLAlchemy create_all on first boot).

Replace with autogenerate revisions once you standardize on Alembic-only DDL.

Revision ID: 001_placeholder
Revises:
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op  # noqa: F401

revision: str = "001_placeholder"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
