"""Factory for creating sinks based on mode."""
from __future__ import annotations

from app.config import get_settings
from app.sinks.frames import CloudFrameSink, FrameSink, LocalRedisFrameSink
from app.sinks.incidents import CloudIncidentSink, IncidentSink, LocalIncidentSink


def get_incident_sink() -> IncidentSink:
    settings = get_settings()
    if settings.agent_mode:
        return CloudIncidentSink()
    return LocalIncidentSink()


def get_frame_sink() -> FrameSink:
    settings = get_settings()
    if settings.agent_mode:
        return CloudFrameSink()
    return LocalRedisFrameSink()
