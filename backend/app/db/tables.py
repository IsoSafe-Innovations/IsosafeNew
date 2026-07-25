"""SQLAlchemy Core table definitions. Schema changes go through Alembic only."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

metadata = sa.MetaData()

cameras = sa.Table(
    "cameras",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("source", sa.Text, nullable=False),  # encrypted at rest if credentials present
    sa.Column("type", sa.Text, nullable=False),  # rtsp | snapshot_url | file
    sa.Column("vertical_profile", sa.Text),
    sa.Column("zones", JSONB, nullable=False, server_default="[]"),
    sa.Column("rules", JSONB, nullable=False, server_default="[]"),
    sa.Column("refresh_secs", sa.REAL, server_default="2"),
    sa.Column("loop_file", sa.Boolean, server_default="true"),
    sa.Column("enabled", sa.Boolean, server_default="true"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
)

detections = sa.Table(
    "detections",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), nullable=False),
    sa.Column("camera_id", sa.Text, nullable=False),
    sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("object_type", sa.Text, nullable=False),
    sa.Column("confidence", sa.REAL, nullable=False),
    sa.Column("track_id", sa.Integer),
    sa.Column("bbox", ARRAY(sa.REAL)),  # [x1, y1, x2, y2] normalized
    sa.Column("zone_ids", ARRAY(sa.Text)),
    sa.Column("plate_text", sa.Text),
    sa.Column("plate_confidence", sa.REAL),
)

incidents = sa.Table(
    "incidents",
    metadata,
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

analytics_hourly = sa.Table(
    "analytics_hourly",
    metadata,
    sa.Column("camera_id", sa.Text, primary_key=True),
    sa.Column("bucket", sa.TIMESTAMP(timezone=True), primary_key=True),
    sa.Column("footfall", sa.Integer, server_default="0"),
    sa.Column("vehicles", JSONB, server_default="{}"),
    sa.Column("avg_queue", sa.REAL, server_default="0"),
    sa.Column("max_queue", sa.Integer, server_default="0"),
    sa.Column("avg_occupancy", sa.REAL, server_default="0"),
    sa.Column("incident_count", sa.Integer, server_default="0"),
)

analytics_daily = sa.Table(
    "analytics_daily",
    metadata,
    sa.Column("camera_id", sa.Text, primary_key=True),
    sa.Column("day", sa.Date, primary_key=True),
    sa.Column("footfall", sa.Integer, server_default="0"),
    sa.Column("vehicles", JSONB, server_default="{}"),
    sa.Column("avg_queue", sa.REAL, server_default="0"),
    sa.Column("max_queue", sa.Integer, server_default="0"),
    sa.Column("avg_occupancy", sa.REAL, server_default="0"),
    sa.Column("incident_count", sa.Integer, server_default="0"),
    sa.Column("peak_hour", sa.Integer),
)

upload_jobs = sa.Table(
    "upload_jobs",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("filename", sa.Text, nullable=False),
    sa.Column("camera_id", sa.Text),
    sa.Column("status", sa.Text, server_default="pending"),  # pending, processing, done, error
    sa.Column("error", sa.Text),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
)

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("email", sa.Text, unique=True, nullable=False),
    sa.Column("password_hash", sa.Text, nullable=False),
    sa.Column("role", sa.Text, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    sa.CheckConstraint("role IN ('admin','operator','viewer')", name="ck_users_role"),
)

audit_log = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("ts", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    sa.Column("user_email", sa.Text),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("target", sa.Text),
    sa.Column("payload", JSONB),
)
