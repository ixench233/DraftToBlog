from __future__ import annotations
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


DEFAULT_CONFIG_PATH = Path.home() / ".markflow" / "config.yaml"
DEFAULT_PICGO_PATH = Path.home() / ".picgo" / "config.json"


class CosCredentials(BaseModel):
    secret_id: str = ""
    secret_key: str = ""
    bucket: str = ""
    region: str = ""
    path: str = "markflow"
    custom_url: str = ""


class LLMConfig(BaseModel):
    provider: Literal["openai", "anthropic", "deepseek", "ollama"] = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    temperature: float = 0.7
    chunk_size: int = 3000


class AppConfig(BaseModel):
    picgo_config: Path = DEFAULT_PICGO_PATH
    cdn_domain: str = ""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    output_dir: Path = Path("./output")
    preset: Literal["hexo", "hugo"] = "hexo"
    cos: CosCredentials = Field(default_factory=CosCredentials)


def load_picgo_cos(picgo_path: Path) -> CosCredentials:
    """Read COS credentials from PicGo config.json."""
    if not picgo_path.exists():
        return CosCredentials()
    try:
        data = json.loads(picgo_path.read_text(encoding="utf-8"))
        tcyun = data.get("picBed", {}).get("tcyun", {})
        raw_path = tcyun.get("path", "") or ""
        # PicGo GUI sometimes stores a local filesystem path — sanitise it
        if "\\" in raw_path or (len(raw_path) > 2 and raw_path[1] == ":"):
            raw_path = "markflow"
        raw_path = raw_path.strip("/").strip() or "markflow"

        return CosCredentials(
            secret_id=tcyun.get("secretId", ""),
            secret_key=tcyun.get("secretKey", ""),
            bucket=tcyun.get("bucket", ""),
            # PicGo GUI uses "area"; PicGo CLI uses "region"
            region=tcyun.get("area") or tcyun.get("region", ""),
            path=raw_path,
            custom_url=tcyun.get("customUrl", ""),
        )
    except Exception:
        return CosCredentials()


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or DEFAULT_CONFIG_PATH
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # Normalise llm sub-dict
    if "llm" in raw and isinstance(raw["llm"], dict):
        raw["llm"] = LLMConfig(**raw["llm"])

    cfg = AppConfig(**raw)

    # Merge PicGo COS credentials (file wins over defaults)
    picgo_cos = load_picgo_cos(cfg.picgo_config)
    # Only overwrite fields that are still empty in cfg.cos
    for f in ("secret_id", "secret_key", "bucket", "region"):
        if not getattr(cfg.cos, f) and getattr(picgo_cos, f):
            object.__setattr__(cfg.cos, f, getattr(picgo_cos, f))
    if not cfg.cos.custom_url and picgo_cos.custom_url:
        object.__setattr__(cfg.cos, "custom_url", picgo_cos.custom_url)

    return cfg


def save_config(cfg: AppConfig, config_path: Path | None = None) -> None:
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "picgo_config": str(cfg.picgo_config),
        "cdn_domain": cfg.cdn_domain,
        "output_dir": str(cfg.output_dir),
        "preset": cfg.preset,
        "llm": {
            "provider": cfg.llm.provider,
            "api_key": cfg.llm.api_key,
            "base_url": cfg.llm.base_url,
            "model": cfg.llm.model,
            "temperature": cfg.llm.temperature,
            "chunk_size": cfg.llm.chunk_size,
        },
    }
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
