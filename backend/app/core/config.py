"""Configuration from environment variables only. No secrets are hardcoded.

Values are read at call time (not import time) so changes to the environment are honoured.
JWT_SECRET has NO default: the application refuses to issue tokens without a >=32 character secret.
"""
import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str
    jwt_secret: str
    jwt_ttl_minutes: int
    data_dir: str
    cors_origins: str


def get_settings() -> Settings:
    e = os.environ
    return Settings(
        database_url=e.get("DATABASE_URL", "sqlite:///./parkiscribe_dev.db"),
        jwt_secret=e.get("JWT_SECRET", ""),
        jwt_ttl_minutes=int(e.get("JWT_TTL_MINUTES", "60")),
        data_dir=e.get("PARKISCRIBE_DATA_DIR", "./data_store"),
        cors_origins=e.get("CORS_ORIGINS", "http://localhost:3000"),
    )
