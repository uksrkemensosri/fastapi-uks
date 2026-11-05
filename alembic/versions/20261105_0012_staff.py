"""Separate staff identities and visits; student tables remain unchanged."""
import sqlalchemy as sa
from alembic import op

revision = '20261105_0012'
down_revision = '20261031_0011'
branch_labels = None
depends_on = None


def upgrade():
    tables=set(sa.inspect(op.get_bind()).get_table_names())
    if 'uks_staff' not in tables:
        op.create_table('uks_staff',sa.Column('id',sa.Integer,primary_key=True),
            sa.Column('school_id',sa.Integer,sa.ForeignKey('schools.id'),nullable=False,index=True),
            sa.Column('name',sa.String(200),nullable=False),sa.Column('position',sa.String(120),nullable=False),
            sa.Column('phone',sa.String(25),nullable=False))
    if 'uks_staff_visits' not in tables:
        op.create_table('uks_staff_visits',sa.Column('id',sa.Integer,primary_key=True),
            sa.Column('school_id',sa.Integer,sa.ForeignKey('schools.id'),nullable=False,index=True),
            sa.Column('staff_id',sa.Integer,sa.ForeignKey('uks_staff.id'),nullable=False,index=True),
            sa.Column('actor_id',sa.Integer,sa.ForeignKey('users.id'),nullable=False),
            sa.Column('visit_date',sa.String(10),nullable=False,index=True),
            sa.Column('record',sa.JSON,nullable=False),sa.Column('whatsapp_status',sa.String(20),nullable=False))


def downgrade():
    raise RuntimeError('Rollback kode saja; pertahankan rekam medis tendik.')
