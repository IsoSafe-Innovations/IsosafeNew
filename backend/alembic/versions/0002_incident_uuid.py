"""Add unique uuid to incidents for agent-side idempotency.

The agent generates the incident UUID; the cloud upserts by it so a retried
POST /agent/v1/incidents never creates a second row (PRD v2 Phase 1a DEMO-FR-21).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("uuid", UUID(as_uuid=True), nullable=True))
    # Nullable + unique: Postgres allows many NULLs, so pre-existing rows are fine.
    op.create_unique_constraint("uq_incidents_uuid", "incidents", ["uuid"])


def downgrade() -> None:
    op.drop_constraint("uq_incidents_uuid", "incidents", type_="unique")
    op.drop_column("incidents", "uuid")
