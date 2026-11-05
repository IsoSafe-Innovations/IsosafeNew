"""Shared request field types.

EmailAddress deliberately avoids pydantic's EmailStr: on-prem deployments use
internal domains (.local, .lan, .internal) that strict deliverability checks
reject.
"""
import uuid as uuid_mod
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]


class IncidentIn(BaseModel):
    id: int | None = None
    camera_id: str | None = None
    ts: str | None = None
    incident_type: str | None = None
    severity: str | None = None
    description: str | None = None
    snapshot_path: str | None = None


class HeartbeatIn(BaseModel):
    status: str | None = None
    uptime: float | None = None
    ts: str | None = None


class AgentCameraHealth(BaseModel):
    camera_id: str
    online: bool = True
    fps: float = 0.0
    reconnects: int = 0
    dropped: int = 0
    analysis: dict[str, Any] | None = None


# PRD v2 Phase 1a §5: heartbeat every 30s carrying process metrics and the
# current health of every camera the agent is running.
class AgentHeartbeatIn(BaseModel):
    agent_version: str | None = None
    uptime_s: float | None = None
    cpu: float | None = None
    mem: float | None = None
    disk_free_gb: float | None = None
    cameras: list[AgentCameraHealth] = Field(default_factory=list)


# PRD v2 Phase 1a §5: the agent-generated incident payload. The agent owns the
# UUID; the cloud upserts by it, so retries are idempotent (DEMO-FR-03/21).
class AgentIncidentIn(BaseModel):
    uuid: uuid_mod.UUID
    camera_id: str
    rule_id: str | None = None
    type: str
    severity: str = "warning"
    ts: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    has_snapshot: bool = False


# The demo agent emits human severities; the incidents table is constrained to
# info/warning/critical, so map before insert.
_SEVERITY_MAP = {
    "critical": "critical",
    "high": "critical",
    "severe": "critical",
    "warning": "warning",
    "medium": "warning",
    "moderate": "warning",
    "info": "info",
    "low": "info",
    "informational": "info",
}


def normalize_severity(value: str | None) -> str:
    return _SEVERITY_MAP.get(str(value or "").strip().lower(), "warning")
