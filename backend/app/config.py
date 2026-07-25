"""Environment-driven settings. Every tunable has a sane default."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infra
    database_url: str = Field(
        default="postgresql+asyncpg://isosafe:isosafe@localhost:5432/isosafe",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    media_root: str = Field(default="/data/media", alias="MEDIA_ROOT")

    # Auth
    jwt_secret: str = Field(default="dev-secret-do-not-use-in-prod", alias="JWT_SECRET")
    access_token_minutes: int = Field(default=30, alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=7, alias="REFRESH_TOKEN_DAYS")
    cors_origins: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")

    # Detection thresholds
    vehicle_confidence: float = Field(default=0.35, alias="VEHICLE_CONFIDENCE")
    person_confidence: float = Field(default=0.40, alias="PERSON_CONFIDENCE")
    plate_confidence: float = Field(default=0.20, alias="PLATE_CONFIDENCE")

    # Pipeline cadence
    process_every_n_frames: int = Field(default=3, alias="PROCESS_EVERY_N_FRAMES")
    ocr_every_n_frames: int = Field(default=5, alias="OCR_EVERY_N_FRAMES")

    # Rule defaults
    stopped_vehicle_seconds: int = Field(default=10, alias="STOPPED_VEHICLE_SECONDS")
    loiter_seconds: int = Field(default=30, alias="LOITER_SECONDS")
    stopped_pixel_delta: int = Field(default=15, alias="STOPPED_PIXEL_DELTA")
    incident_cooldown_secs: int = Field(default=30, alias="INCIDENT_COOLDOWN_SECS")
    queue_zone_threshold: int = Field(default=5, alias="QUEUE_ZONE_THRESHOLD")

    # Capacity
    max_cameras_per_node: int = Field(default=64, alias="MAX_CAMERAS_PER_NODE")
    inference_workers: int = Field(default=2, alias="INFERENCE_WORKERS")
    frame_jpeg_quality: int = Field(default=70, alias="FRAME_JPEG_QUALITY")
    dashboard_max_fps: float = Field(default=10.0, alias="DASHBOARD_MAX_FPS")
    file_playback_fps: float = Field(default=0.0, alias="FILE_PLAYBACK_FPS")
    inference_batch_size: int = Field(default=8, alias="INFERENCE_BATCH_SIZE")
    inference_max_dim: int = Field(default=640, alias="INFERENCE_MAX_DIM")

    # Retention
    retention_detections_days: int = Field(default=90, alias="RETENTION_DETECTIONS_DAYS")
    retention_snapshots_days: int = Field(default=30, alias="RETENTION_SNAPSHOTS_DAYS")

    # Models
    yolo_model: str = Field(default="yolov8n.pt", alias="YOLO_MODEL")
    yolo_device: str = Field(default="cpu", alias="YOLO_DEVICE")

    # Alerts
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="alerts@isosafe.local", alias="SMTP_FROM")
    alert_email_to: str = Field(default="", alias="ALERT_EMAIL_TO")
    alert_email_min_severity: str = Field(default="critical", alias="ALERT_EMAIL_MIN_SEVERITY")
    webhook_url: str = Field(default="", alias="WEBHOOK_URL")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")

    # AI (optional)
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    # Security / limits
    fernet_key: str = Field(default="", alias="FERNET_KEY")
    upload_max_mb: int = Field(default=500, alias="UPLOAD_MAX_MB")

    # Resource guards
    worker_memory_limit_mb: int = Field(default=2048, alias="WORKER_MEMORY_LIMIT_MB")
    disk_min_free_gb: float = Field(default=2.0, alias="DISK_MIN_FREE_GB")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        """psycopg2 URL for Alembic and synchronous helpers."""
        return self.database_url.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    return Settings()
