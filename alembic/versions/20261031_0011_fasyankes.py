"""Add collaboration history and in-app guardian notifications only.

Based on the deployed 0008 lineage. Retired, untracked Dokter Kecil migrations
must not be included in the release. Upgrade explicitly to 20261031_0011.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261031_0011'
down_revision = '20260924_0008'
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'fasyankes_cases' not in tables:
        op.create_table('fasyankes_cases',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('school_id', sa.Integer(), sa.ForeignKey('schools.id'), nullable=False, index=True),
            sa.Column('patient_id', sa.String(50), sa.ForeignKey('patients.id'), nullable=False, index=True),
            sa.Column('referral_id', sa.Integer(), sa.ForeignKey('bpjs_referrals.id'), unique=True),
            sa.Column('uks_visit_id', sa.Integer(), sa.ForeignKey('uks_visits.id')),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('data', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    if 'fasyankes_revisions' not in tables:
        op.create_table('fasyankes_revisions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('case_id', sa.Integer(), sa.ForeignKey('fasyankes_cases.id'), nullable=False, index=True),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('action', sa.String(50), nullable=False),
            sa.Column('snapshot', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('case_id','version'))
    if 'fasyankes_notifications' not in tables:
        op.create_table('fasyankes_notifications',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('case_id', sa.Integer(), sa.ForeignKey('fasyankes_cases.id'), nullable=False, index=True),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('recipient_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
            sa.Column('read_at', sa.DateTime(timezone=True)),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('case_id','version','recipient_id'))


def downgrade():
    raise RuntimeError('Keep collaboration data and history when rolling back application code.')
