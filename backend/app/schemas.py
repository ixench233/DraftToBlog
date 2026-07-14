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


class ProcessRequest(BaseModel):
    finding_ids: list[str] = Field(default_factory=list)
    improve_structure: bool = True


class ConfigStatus(BaseModel):
    official_ai_ready: bool
    user_ai_allowed: bool
    cos_ready: bool
    picgo_configured: bool
    mock_mode: bool

