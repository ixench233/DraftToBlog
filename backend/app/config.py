from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "DraftToBlog")
    app_env: str = os.getenv("APP_ENV", "development")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    cors_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if item.strip()
    )
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "20"))
    temp_dir: Path = ROOT_DIR / os.getenv("TEMP_DIR", "data/tmp")
    task_ttl_minutes: int = int(os.getenv("TASK_TTL_MINUTES", "60"))
    official_ai_enabled: bool = _as_bool(os.getenv("OFFICIAL_AI_ENABLED"))
    official_ai_base_url: str = os.getenv("OFFICIAL_AI_BASE_URL", "")
    official_ai_api_key: str = os.getenv("OFFICIAL_AI_API_KEY", "")
    official_ai_model: str = os.getenv("OFFICIAL_AI_MODEL", "")
    allow_user_ai_config: bool = _as_bool(
        os.getenv("ALLOW_USER_AI_CONFIG"), default=True
    )
    picgo_bin: str = os.getenv("PICGO_BIN", "picgo")
    picgo_config_path: str = os.getenv("PICGO_CONFIG_PATH", "")
    cos_bucket: str = os.getenv("TENCENT_COS_BUCKET", "")
    cos_region: str = os.getenv("TENCENT_COS_REGION", "")
    cos_public_base_url: str = os.getenv("TENCENT_COS_PUBLIC_BASE_URL", "")

    @property
    def official_ai_ready(self) -> bool:
        return bool(
            self.official_ai_enabled
            and self.official_ai_base_url
            and self.official_ai_api_key
            and self.official_ai_model
        )

    @property
    def cos_ready(self) -> bool:
        return bool(self.cos_bucket and self.cos_region and self.cos_public_base_url)


settings = Settings()
settings.temp_dir.mkdir(parents=True, exist_ok=True)

