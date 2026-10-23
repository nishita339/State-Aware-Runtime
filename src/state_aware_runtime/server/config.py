"""
Production Server Configuration.

Handles environment-based configuration for cloud-native distributed deployment
capable of handling millions of real-time concurrent agent sessions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerConfig:
    """Production server settings with environment variable overrides."""

    # Networking
    host: str = field(default_factory=lambda: os.getenv("SADR_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("SADR_PORT", "8000")))
    workers: int = field(default_factory=lambda: int(os.getenv("SADR_WORKERS", "4")))
    cors_origins: list[str] = field(default_factory=lambda: os.getenv("SADR_CORS", "*").split(","))

    # Distributed State & Cache
    redis_url: str = field(default_factory=lambda: os.getenv("SADR_REDIS_URL", "redis://localhost:6379/0"))
    use_redis_cache: bool = field(default_factory=lambda: os.getenv("SADR_USE_REDIS", "false").lower() == "true")

    # Database & Storage
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "SADR_DATABASE_URL", "sqlite+aiosqlite:///./state/sadr_production.db"
        )
    )
    storage_dir: Path = field(default_factory=lambda: Path(os.getenv("SADR_STORAGE_DIR", "./state")))
    log_dir: Path = field(default_factory=lambda: Path(os.getenv("SADR_LOG_DIR", "./logs")))
    workspace_dir: Path = field(default_factory=lambda: Path(os.getenv("SADR_WORKSPACE_DIR", "./workspace")))

    # Blob Object Storage (MinIO / AWS S3)
    s3_endpoint: str = field(default_factory=lambda: os.getenv("SADR_S3_ENDPOINT", ""))
    s3_bucket: str = field(default_factory=lambda: os.getenv("SADR_S3_BUCKET", "sadr-checkpoints"))
    s3_access_key: str = field(default_factory=lambda: os.getenv("SADR_S3_ACCESS_KEY", ""))
    s3_secret_key: str = field(default_factory=lambda: os.getenv("SADR_S3_SECRET_KEY", ""))

    # Multi-tenancy & Quotas
    default_tenant_id: str = "default_tenant"
    max_concurrent_sessions_per_tenant: int = field(
        default_factory=lambda: int(os.getenv("SADR_MAX_SESSIONS_PER_TENANT", "500"))
    )
    rate_limit_per_second: int = field(
        default_factory=lambda: int(os.getenv("SADR_RATE_LIMIT", "1000"))
    )
    api_key_auth_enabled: bool = field(
        default_factory=lambda: os.getenv("SADR_AUTH_ENABLED", "false").lower() == "true"
    )

    # Telemetry
    enable_metrics: bool = True
    log_level: str = field(default_factory=lambda: os.getenv("SADR_LOG_LEVEL", "INFO"))

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
