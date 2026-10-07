"""Store consent and reviewer confirmation for AI-assisted meeting records."""
from alembic import op
import sqlalchemy as sa
revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None
def upgrade():
    for name in ["ai_assisted","consent_recorded","ai_reviewed"]:
        op.add_column("meetings",sa.Column(name,sa.Boolean(),nullable=False,server_default=sa.false()))
def downgrade():
    for name in ["ai_reviewed","consent_recorded","ai_assisted"]: op.drop_column("meetings",name)
