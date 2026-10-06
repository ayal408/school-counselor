"""Initial schema; no sample or user data."""
from alembic import op
import sqlalchemy as sa
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("email", sa.String(254), nullable=False, unique=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("password_hash", sa.Text(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False))
    op.create_table("students", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("name", sa.Text(), nullable=False), sa.Column("classroom", sa.Text(), nullable=False), sa.Column("referral", sa.Text(), nullable=False), sa.Column("archived", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_students_owner_id", "students", ["owner_id"])
    op.create_table("meetings", sa.Column("id", sa.String(36), primary_key=True), sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id"), nullable=False), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("notes", sa.Text(), nullable=False), sa.Column("summary", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_meetings_student_id", "meetings", ["student_id"])
    op.create_table("refresh_sessions", sa.Column("token_hash", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])
    op.create_table("audit_events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), nullable=False), sa.Column("action", sa.String(40), nullable=False), sa.Column("record_id", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
def downgrade():
    for name in ["audit_events", "refresh_sessions", "meetings", "students", "users"]: op.drop_table(name)
