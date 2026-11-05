"""Validated, portable per-camera analysis settings."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Region(BaseModel):
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1)
    y2: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("Region must have positive width and height")
        return self


class AnalysisOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: Literal["fast", "balanced", "detail"] = "fast"
    input_size: Literal[640, 960, 1280] | None = None
    tiled: bool = False
    regions: list[Region] = Field(default_factory=list, max_length=4)
    tracker: Literal["centroid", "bytetrack", "botsort"] = "centroid"
    person_confidence: float = Field(default=.35, ge=.1, le=.95)
    vehicle_confidence: float = Field(default=.35, ge=.1, le=.95)
    confirmation_frames: int = Field(default=3, ge=1, le=15)
    plate_reading: bool = True


def resolve_options(value: dict | None = None) -> dict:
    from app.config import get_settings

    options = AnalysisOptions.model_validate(value or {}).model_dump()
    settings = get_settings()
    preset = options["preset"]
    options["model"] = settings.yolo_model if preset == "fast" else settings.yolo_detail_model
    options["input_size"] = options["input_size"] or (640 if preset == "fast" else 960 if preset == "balanced" else 1280)
    return options
