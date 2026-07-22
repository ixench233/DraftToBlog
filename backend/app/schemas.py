from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Finding(BaseModel):
    id: str
    kind: str
    label: str
    original: str
    replacement: str
    start: int
    end: int
    risk: Literal["low", "medium", "high"]
    accepted: bool = True


class DocumentStats(BaseModel):
    characters: int
    paragraphs: int
    images: int
    findings: int


class DocumentResponse(BaseModel):
    id: str
    filename: str
    source_type: Literal["markdown", "docx", "pdf"]
    status: Literal["ready", "processed"]
    original_content: str
    processed_content: str
    stats: DocumentStats
    findings: list[Finding]
    warnings: list[str] = Field(default_factory=list)
    assets: list["Asset"] = Field(default_factory=list)


class Asset(BaseModel):
    filename: str
    local_path: str
    status: Literal["pending", "uploaded", "failed"] = "pending"
    url: str = ""
    provider: str = ""
    error: str = ""


class AIConfig(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)


class ProcessRequest(BaseModel):
    finding_ids: list[str] = Field(default_factory=list)
    improve_structure: bool = True
    ai_config: AIConfig | None = None


class ConfigStatus(BaseModel):
    official_ai_ready: bool
    user_ai_allowed: bool
    cos_ready: bool
    picgo_configured: bool
    mock_mode: bool
    app_public_url: str
    frontend_public_url: str
    deployment_configured: bool
    app_secret_configured: bool

