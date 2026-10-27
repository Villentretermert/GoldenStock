"""Infrastructure baseline. No tenant financial data exists in this revision."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("worker_heartbeats",
                    sa.Column("worker_id", sa.String(100), primary_key=True),
                    sa.Column("last_seen", sa.Float(), nullable=False))


def downgrade():
    op.drop_table("worker_heartbeats")
