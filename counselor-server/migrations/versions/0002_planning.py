"""Add calendar and encrypted follow-up tasks."""
from alembic import op
import sqlalchemy as sa
revision="0002"
down_revision="0001"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("appointments", sa.Column("id",sa.String(36),primary_key=True),sa.Column("student_id",sa.String(36),sa.ForeignKey("students.id"),nullable=False),sa.Column("starts_at",sa.DateTime(timezone=True),nullable=False),sa.Column("ends_at",sa.DateTime(timezone=True),nullable=False),sa.Column("status",sa.String(20),nullable=False))
    op.create_index("ix_appointments_student_id","appointments",["student_id"])
    op.create_table("tasks",sa.Column("id",sa.String(36),primary_key=True),sa.Column("student_id",sa.String(36),sa.ForeignKey("students.id"),nullable=False),sa.Column("title",sa.Text(),nullable=False),sa.Column("due_at",sa.DateTime(timezone=True),nullable=False),sa.Column("status",sa.String(20),nullable=False))
    op.create_index("ix_tasks_student_id","tasks",["student_id"])
def downgrade():
    op.drop_table("tasks");op.drop_table("appointments")
