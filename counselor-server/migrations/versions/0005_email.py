"""System Gmail connection, encrypted durable outbox and account email tokens."""
from alembic import op
import sqlalchemy as sa
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None
def upgrade():
    op.add_column('users',sa.Column('email_verified',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('email_settings',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('generation',sa.Integer(),nullable=False),sa.Column('sender_email',sa.String(254),nullable=False),sa.Column('sender_name',sa.String(100),nullable=False),sa.Column('reply_to',sa.String(254),nullable=False),sa.Column('signature',sa.Text(),nullable=False),sa.Column('refresh_token',sa.Text(),nullable=True),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('email_consents',sa.Column('state_hash',sa.String(64),primary_key=True),sa.Column('generation',sa.Integer(),nullable=False),sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('session_version',sa.Integer(),nullable=False),sa.Column('verifier',sa.Text(),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('email_outbox',sa.Column('id',sa.String(36),primary_key=True),sa.Column('recipient',sa.String(254),nullable=False),sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=True),sa.Column('kind',sa.String(30),nullable=False),sa.Column('payload',sa.Text(),nullable=True),sa.Column('status',sa.String(20),nullable=False),sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('failure_code',sa.String(40),nullable=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('next_attempt',sa.DateTime(timezone=True),nullable=False),sa.Column('sent_at',sa.DateTime(timezone=True),nullable=True))
    op.create_index('ix_email_outbox_pending','email_outbox',['status','next_attempt'])
    op.create_table('account_email_tokens',sa.Column('token_hash',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('purpose',sa.String(20),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_account_email_tokens_user_id','account_email_tokens',['user_id'])
def downgrade():
    for table in ['account_email_tokens','email_outbox','email_consents','email_settings']:op.drop_table(table)
    op.drop_column('users','email_verified')
