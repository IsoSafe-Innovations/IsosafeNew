"""Initial schema: all tables, hypertables, indexes, retention policies.

Revision ID: 0001
Revises:
Create Date: 2026-07-02

"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

RETENTION_DETECTIONS_DAYS = int(os.environ.get("RETENTION_DETECTIONS_DAYS", "90"))


def _timescale_available(conn) -> bool:
    row = conn.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    has_timescale = _timescale_available(conn)
    if has_timescale:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "cameras",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("vertical_profile", sa.Text),
        sa.Column("zones", JSONB, nullable=False, server_default="[]"),
        sa.Column("rules", JSONB, nullable=False, server_default="[]"),
        sa.Column("refresh_secs", sa.REAL, server_default="2"),
        sa.Column("loop_file", sa.Boolean, server_default="true"),
        sa.Column("enabled", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # Hypertable: no PK (Timescale requires partition column in unique constraints).
    op.create_table(
        "detections",
        sa.Column("id", sa.BigInteger, sa.Identity(), nullable=False),
        sa.Column("camera_id", sa.Text, nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("object_type", sa.Text, nullable=False),
        sa.Column("confidence", sa.REAL, nullable=False),
        sa.Column("track_id", sa.Integer),
        sa.Column("bbox", ARRAY(sa.REAL)),
        sa.Column("zone_ids", ARRAY(sa.Text)),
        sa.Column("plate_text", sa.Text),
        sa.Column("plate_confidence", sa.REAL),
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("camera_id", sa.Text, nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("incident_type", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("snapshot_path", sa.Text),
        sa.Column("clip_path", sa.Text),
        sa.Column("status", sa.Text, server_default="open"),
        sa.Column("assigned_to", sa.Text),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("resolution_notes", sa.Text),
        sa.CheckConstraint("severity IN ('info','warning','critical')", name="ck_incidents_severity"),
        sa.CheckConstraint(
            "status IN ('open','investigating','resolved','closed')", name="ck_incidents_status"
        ),
    )

    op.create_table(
        "analytics_hourly",
        sa.Column("camera_id", sa.Text, nullable=False),
        sa.Column("bucket", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("footfall", sa.Integer, server_default="0"),
        sa.Column("vehicles", JSONB, server_default="{}"),
        sa.Column("avg_queue", sa.REAL, server_default="0"),
        sa.Column("max_queue", sa.Integer, server_default="0"),
        sa.Column("avg_occupancy", sa.REAL, server_default="0"),
        sa.Column("incident_count", sa.Integer, server_default="0"),
        sa.PrimaryKeyConstraint("camera_id", "bucket"),
    )

    op.create_table(
        "analytics_daily",
        sa.Column("camera_id", sa.Text, nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("footfall", sa.Integer, server_default="0"),
        sa.Column("vehicles", JSONB, server_default="{}"),
        sa.Column("avg_queue", sa.REAL, server_default="0"),
        sa.Column("max_queue", sa.Integer, server_default="0"),
        sa.Column("avg_occupancy", sa.REAL, server_default="0"),
        sa.Column("incident_count", sa.Integer, server_default="0"),
        sa.Column("peak_hour", sa.Integer),
        sa.PrimaryKeyConstraint("camera_id", "day"),
    )

    op.create_table(
        "upload_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("camera_id", sa.Text),
        sa.Column("status", sa.Text, server_default="pending"),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('admin','operator','viewer')", name="ck_users_role"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("user_email", sa.Text),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target", sa.Text),
        sa.Column("payload", JSONB),
    )

    # Indexes
    op.create_index("ix_detections_camera_ts", "detections", ["camera_id", sa.text("ts DESC")])
    op.create_index("ix_incidents_camera_ts", "incidents", ["camera_id", sa.text("ts DESC")])
    op.create_index("ix_incidents_status_severity", "incidents", ["status", "severity"])
    op.execute(
        "CREATE INDEX ix_detections_plate_trgm ON detections "
        "USING GIN (plate_text gin_trgm_ops) WHERE plate_text IS NOT NULL"
    )

    if has_timescale:
        op.execute(
            "SELECT create_hypertable('detections', 'ts', "
            "chunk_time_interval => INTERVAL '1 day', migrate_data => true)"
        )
        op.execute(
            "SELECT create_hypertable('analytics_hourly', 'bucket', "
            "chunk_time_interval => INTERVAL '7 days', migrate_data => true)"
        )
        op.execute(
            f"SELECT add_retention_policy('detections', INTERVAL '{RETENTION_DETECTIONS_DAYS} days')"
        )


def downgrade() -> None:
    for table in (
        "audit_log",
        "users",
        "upload_jobs",
        "analytics_daily",
        "analytics_hourly",
        "incidents",
        "detections",
        "cameras",
    ):
        op.drop_table(table)
