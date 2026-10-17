"""Persistent identities and immutable analysis inputs."""
from pathlib import Path
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute((Path(__file__).with_suffix(".sql")).read_text())

def downgrade():
    # Source and result history must not be destroyed by an accidental downgrade.
    raise RuntimeError("Destructive downgrade disabled; restore an isolated backup instead")
