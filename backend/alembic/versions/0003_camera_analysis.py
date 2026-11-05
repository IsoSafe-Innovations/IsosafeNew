"""Per-camera analysis options.

Revision ID: 0003_camera_analysis
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_camera_analysis"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cameras", sa.Column("analysis_config", JSONB, nullable=False, server_default="{}"))
    from sqlalchemy.dialects.postgresql import UUID
    op.create_table("crossing_events",
        sa.Column("id",sa.BigInteger,sa.Identity(),primary_key=True),
        sa.Column("camera_id",sa.Text,nullable=False),
        sa.Column("session_id",UUID(as_uuid=True),nullable=False),
        sa.Column("rule_id",sa.Text,nullable=False),
        sa.Column("track_id",sa.Integer,nullable=False),
        sa.Column("direction",sa.Text,nullable=False),
        sa.Column("count_as",sa.Text,nullable=False),
        sa.Column("object_type",sa.Text,nullable=False),
        sa.Column("ts",sa.TIMESTAMP(timezone=True),nullable=False),
        sa.UniqueConstraint("camera_id","session_id","rule_id","track_id","direction",name="uq_crossing_track"))
    op.create_index("ix_crossing_events_ts","crossing_events",["ts"])


def downgrade():
    op.drop_table("crossing_events")
    op.drop_column("cameras", "analysis_config")
