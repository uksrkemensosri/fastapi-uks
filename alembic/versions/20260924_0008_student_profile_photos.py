"""Add optional local student profile photo paths.

Revision ID: 20260924_0008
Revises: 20260924_0007
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260924_0008"
down_revision: Union[str, Sequence[str], None] = "20260924_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("patients")}
    if "profile_photo_path" not in columns:
        op.add_column("patients", sa.Column("profile_photo_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("patients")}
    if "profile_photo_path" in columns:
        op.drop_column("patients", "profile_photo_path")
