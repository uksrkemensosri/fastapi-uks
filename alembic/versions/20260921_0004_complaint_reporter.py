"""Add reporter name to public student complaints.

Revision ID: 20260921_0004
Revises: 20260918_0003
Create Date: 2026-09-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260921_0004"
down_revision: Union[str, Sequence[str], None] = "20260918_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("student_complaints")}
    if "reporter_name" not in columns:
        op.add_column(
            "student_complaints",
            sa.Column("reporter_name", sa.String(length=150), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("student_complaints")}
    if "reporter_name" in columns:
        op.drop_column("student_complaints", "reporter_name")
