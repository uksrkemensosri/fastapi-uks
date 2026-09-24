"""Track completion of scheduled BPJS referral controls.

Revision ID: 20260924_0006
Revises: 20260924_0005
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260924_0006"
down_revision: Union[str, Sequence[str], None] = "20260924_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("bpjs_referrals")}
    if "control_done" not in columns:
        op.add_column(
            "bpjs_referrals",
            sa.Column("control_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("bpjs_referrals")}
    if "control_done" in columns:
        op.drop_column("bpjs_referrals", "control_done")
