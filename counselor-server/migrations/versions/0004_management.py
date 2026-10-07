"""Settings, administrators, read-only sharing, MFA and backup import receipts."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None
def upgrade():
    for name, type_, default in [('role',sa.String(20),'counselor'),('session_version',sa.Integer(),'0'),('mfa_last_step',sa.Integer(),'-1'),('failed_logins',sa.Integer(),'0'),('recovery_hashes',sa.Text(),'[]')]:
        op.add_column('users',sa.Column(name,type_,nullable=False,server_default=default))
    for name,type_ in [('mfa_secret',sa.Text()),('mfa_pending',sa.Text()),('mfa_pending_until',sa.DateTime(timezone=True)),('locked_until',sa.DateTime(timezone=True)),('last_backup',sa.DateTime(timezone=True))]:
        op.add_column('users',sa.Column(name,type_,nullable=True))
    # Existing installations have no role information. Promote one deterministic account.
    op.execute("UPDATE users SET role='admin' WHERE id=(SELECT id FROM users WHERE active=true ORDER BY email LIMIT 1)")
    op.create_table('student_shares',sa.Column('student_id',sa.String(36),sa.ForeignKey('students.id'),primary_key=True),sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),primary_key=True))
    op.create_table('ai_configs',sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),primary_key=True),sa.Column('provider',sa.String(20),primary_key=True),sa.Column('key',sa.Text(),nullable=True),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('preferred',sa.Boolean(),nullable=False),sa.Column('transcription_model',sa.String(120),nullable=False),sa.Column('summary_model',sa.String(120),nullable=False))
    op.create_table('backup_imports',sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),primary_key=True),sa.Column('digest',sa.String(64),primary_key=True))
def downgrade():
    for table in ['backup_imports','ai_configs','student_shares']: op.drop_table(table)
    for name in ['last_backup','locked_until','mfa_pending_until','mfa_pending','mfa_secret','recovery_hashes','failed_logins','mfa_last_step','session_version','role']: op.drop_column('users',name)
