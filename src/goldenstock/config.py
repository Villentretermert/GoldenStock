"""Explicit configuration; no cloud AI endpoint is enabled by default."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GS_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/goldenstock-dev.db"
    inference_url: str = "http://inference:11434"
    data_dir: Path = Path("data")
    worker_id: str = "worker-1"
    heartbeat_interval: float = 5.0
    heartbeat_timeout: float = 30.0
    public_url: str = 'http://127.0.0.1:8081'
    secure_cookie: bool = False  # Enable with TLS during GS-023.
    sec_contact: str = ''  # Deployment-only User-Agent contact, never browser input.
    max_file_bytes: int = 50 * 1024 * 1024

    @field_validator('public_url')
    @classmethod
    def origin_only(cls, value):
        url = urlsplit(value)
        if url.scheme not in {'http', 'https'} or not url.hostname or url.path not in {'', '/'} or url.query or url.fragment or url.username:
            raise ValueError('Expected a web origin')
        return value.rstrip('/')

    @field_validator("inference_url")
    @classmethod
    def local_inference_only(cls, value: str) -> str:
        url = urlsplit(value)
        if (url.scheme != "http" or url.hostname not in {"inference", "localhost", "127.0.0.1", "::1"}
                or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError("Inference must use the fixed internal service or loopback")
        return value.rstrip("/")

    @field_validator("heartbeat_interval", "heartbeat_timeout")
    @classmethod
    def positive(cls, value: float) -> float:
        if not 0 < value <= 3600:
            raise ValueError("Heartbeat settings must be positive finite seconds <= 3600")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
