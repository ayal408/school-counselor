"""Casework, immutable meeting revisions and consent-controlled sharing."""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone
revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None
def upgrade():
    current=datetime.now(timezone.utc);year=current.year if current.month>=9 else current.year-1
    op.add_column('students',sa.Column('school_year',sa.String(9),nullable=False,server_default=f'{year}-{year+1}'))
    op.add_column('meetings',sa.Column('version',sa.Integer(),nullable=False,server_default='1'))
    op.add_column('meetings',sa.Column('document',sa.Text(),nullable=True))
    op.add_column('meetings',sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_table('case_records',sa.Column('id',sa.String(36),primary_key=True),sa.Column('student_id',sa.String(36),sa.ForeignKey('students.id'),nullable=False),sa.Column('kind',sa.String(20),nullable=False),sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.Column('document',sa.Text(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_case_records_student_id','case_records',['student_id'])
    op.create_index('ix_case_records_kind','case_records',['kind'])
    op.create_table('meeting_revisions',sa.Column('meeting_id',sa.String(36),sa.ForeignKey('meetings.id'),primary_key=True),sa.Column('version',sa.Integer(),primary_key=True),sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id'),nullable=True),sa.Column('document',sa.Text(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('case_consents',sa.Column('id',sa.String(36),primary_key=True),sa.Column('student_id',sa.String(36),sa.ForeignKey('students.id'),nullable=False),sa.Column('purpose',sa.String(20),nullable=False),sa.Column('recipient',sa.String(36),nullable=False),sa.Column('granted_at',sa.DateTime(timezone=True),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('revoked',sa.Boolean(),nullable=False),sa.Column('evidence',sa.Text(),nullable=False),sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False))
    op.create_index('ix_case_consents_student_id','case_consents',['student_id'])
    op.create_table('case_transfers',sa.Column('id',sa.String(36),primary_key=True),sa.Column('student_id',sa.String(36),sa.ForeignKey('students.id'),nullable=False),sa.Column('from_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('to_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('reason',sa.Text(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('completed_at',sa.DateTime(timezone=True),nullable=True))
    op.create_index('ix_case_transfers_student_id','case_transfers',['student_id'])
def downgrade():
    for t in ['case_transfers','case_consents','meeting_revisions','case_records']:op.drop_table(t)
    for c in ['updated_at','document','version']:op.drop_column('meetings',c)
    op.drop_column('students','school_year')
