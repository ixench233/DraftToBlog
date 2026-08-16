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
    app_secret_key: str = os.getenv("APP_SECRET_KEY", "")
    app_public_url: str = os.getenv("APP_PUBLIC_URL", "")
    frontend_public_url: str = os.getenv("FRONTEND_PUBLIC_URL", "")
    cors_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if item.strip()
    )
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "0"))
    temp_dir: Path = ROOT_DIR / os.getenv("TEMP_DIR", "data/tmp")
    task_ttl_minutes: int = int(os.getenv("TASK_TTL_MINUTES", "60"))
    official_ai_enabled: bool = _as_bool(os.getenv("OFFICIAL_AI_ENABLED"))
    official_ai_base_url: str = os.getenv("OFFICIAL_AI_BASE_URL", "")
    official_ai_api_key: str = os.getenv("OFFICIAL_AI_API_KEY", "")
    official_ai_model: str = os.getenv("OFFICIAL_AI_MODEL", "")
    official_ai_daily_request_limit: int = int(os.getenv("OFFICIAL_AI_DAILY_REQUEST_LIMIT", "100"))
    official_ai_max_input_chars: int = int(os.getenv("OFFICIAL_AI_MAX_INPUT_CHARS", "30000"))
    official_ai_timeout_seconds: float = float(os.getenv("OFFICIAL_AI_TIMEOUT_SECONDS", "300"))
    official_ai_trust_env: bool = _as_bool(os.getenv("OFFICIAL_AI_TRUST_ENV"), default=True)
    allow_user_ai_config: bool = _as_bool(
        os.getenv("ALLOW_USER_AI_CONFIG"), default=True
    )
    picgo_bin: str = os.getenv("PICGO_BIN", "picgo")
    picgo_config_path: str = os.getenv("PICGO_CONFIG_PATH", "")
    upload_provider: str = os.getenv("UPLOAD_PROVIDER", "auto").strip().lower()
    cos_secret_id: str = os.getenv("TENCENT_COS_SECRET_ID", "")
    cos_secret_key: str = os.getenv("TENCENT_COS_SECRET_KEY", "")
    cos_bucket: str = os.getenv("TENCENT_COS_BUCKET", "")
    cos_region: str = os.getenv("TENCENT_COS_REGION", "")
    cos_public_base_url: str = os.getenv("TENCENT_COS_PUBLIC_BASE_URL", "")
    cos_path_prefix: str = os.getenv("TENCENT_COS_PATH_PREFIX", "draft-to-blog/")
    cos_auto_delete_days: int = int(os.getenv("TENCENT_COS_AUTO_DELETE_DAYS", "7"))
    cos_upload_workers: int = int(os.getenv("TENCENT_COS_UPLOAD_WORKERS", "2"))
    deploy_host: str = os.getenv("DEPLOY_HOST", "")
    deploy_port: int = int(os.getenv("DEPLOY_PORT", "22"))
    deploy_user: str = os.getenv("DEPLOY_USER", "")
    deploy_password: str = os.getenv("DEPLOY_PASSWORD", os.getenv("PASSWORD", ""))
    deploy_path: str = os.getenv("DEPLOY_PATH", "")
    deploy_ssh_key_path: str = os.getenv("DEPLOY_SSH_KEY_PATH", "")
    deploy_domain: str = os.getenv("DEPLOY_DOMAIN", "")
    deploy_ssl_email: str = os.getenv("DEPLOY_SSL_EMAIL", "")
    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "123456")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "draft_to_blog")
    default_user_name: str = os.getenv("DEFAULT_USER_NAME", "demo_user")
    default_user_display_name: str = os.getenv("DEFAULT_USER_DISPLAY_NAME", "Demo User")
    default_user_password: str = os.getenv("DEFAULT_USER_PASSWORD", "123456")
    default_admin_name: str = os.getenv("DEFAULT_ADMIN_NAME", "admin")
    default_admin_display_name: str = os.getenv("DEFAULT_ADMIN_DISPLAY_NAME", "Administrator")
    default_admin_password: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123456")

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
        return bool(
            self.cos_secret_id
            and self.cos_secret_key
            and self.cos_bucket
            and self.cos_region
            and self.cos_public_base_url
        )

    @property
    def picgo_ready(self) -> bool:
        return bool(self.picgo_bin and self.picgo_config_path and Path(self.picgo_config_path).is_file())

    @property
    def deployment_configured(self) -> bool:
        return bool(self.deploy_host and self.deploy_user and self.deploy_path)

    @property
    def remote_upload_ready(self) -> bool:
        return bool(
            self.deploy_host
            and self.deploy_user
            and (self.deploy_password or self.deploy_ssh_key_path)
            and self.cos_ready
        )


settings = Settings()
settings.temp_dir.mkdir(parents=True, exist_ok=True)

