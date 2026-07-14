from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .config import settings
from .schemas import ConfigStatus, DocumentResponse, ProcessRequest
from .services.document_service import analyze_upload, create_demo, process_document
from .services.export_service import export_document
from .storage import store


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.cleanup_expired()
    yield


app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description="Convert PDF, DOCX and Markdown drafts into publishable content.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "version": "0.1.0"}


@app.get("/api/config/status", response_model=ConfigStatus)
def config_status() -> ConfigStatus:
    return ConfigStatus(
        official_ai_ready=settings.official_ai_ready,
        user_ai_allowed=settings.allow_user_ai_config,
        cos_ready=settings.cos_ready,
        picgo_configured=bool(settings.picgo_config_path),
        mock_mode=not (settings.official_ai_ready and settings.cos_ready),
    )


@app.post("/api/documents/analyze", response_model=DocumentResponse)
async def analyze_document(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "document"
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not content:
        raise HTTPException(status_code=400, detail="文件为空，请重新选择。")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"文件不能超过 {settings.max_upload_mb} MB。",
        )
    try:
        return analyze_upload(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/documents/demo", response_model=DocumentResponse)
def demo_document() -> dict:
    return create_demo()


@app.get("/api/documents/{task_id}", response_model=DocumentResponse)
def get_document(task_id: str) -> dict:
    payload = store.get(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail="任务不存在或已过期。")
    return payload


@app.post("/api/documents/{task_id}/process", response_model=DocumentResponse)
def process(task_id: str, request: ProcessRequest) -> dict:
    try:
        return process_document(
            task_id,
            finding_ids=request.finding_ids,
            improve_structure=request.improve_structure,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在或已过期。") from exc


@app.get("/api/documents/{task_id}/export/{format_name}")
def export(task_id: str, format_name: str) -> Response:
    payload = store.get(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail="任务不存在或已过期。")
    try:
        content, filename, media_type = export_document(payload, format_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    encoded = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )

