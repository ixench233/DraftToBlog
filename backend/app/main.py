from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from .config import settings
from .schemas import ConfigStatus, DocumentResponse, ProcessRequest
from .services.document_service import analyze_upload, create_demo, process_document
from .services.export_service import export_document
from .services.ai_service import AIServiceError
from .services.media_service import cleanup_expired_cos_objects
from .storage import store


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.cleanup_expired()
    try:
        cleanup_expired_cos_objects()
    except Exception:
        # A storage outage must not prevent the API from starting.
        pass
    yield


app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description="Convert PDF, DOCX and Markdown drafts into publishable content.",
    lifespan=lifespan,
    servers=[{"url": settings.app_public_url}] if settings.app_public_url else None,
)
allowed_origins = set(settings.cors_origins)
if settings.frontend_public_url:
    allowed_origins.add(settings.frontend_public_url.rstrip("/"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
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
        picgo_configured=settings.picgo_ready,
        mock_mode=not settings.official_ai_ready,
        app_public_url=settings.app_public_url,
        frontend_public_url=settings.frontend_public_url,
        deployment_configured=settings.deployment_configured,
        app_secret_configured=bool(settings.app_secret_key),
    )


@app.post("/api/documents/analyze", response_model=DocumentResponse)
async def analyze_document(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "document"
    limit_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read(limit_bytes + 1) if limit_bytes > 0 else await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空，请重新选择。")
    if limit_bytes > 0 and len(content) > limit_bytes:
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


@app.get("/api/documents/{task_id}/assets/{filename}")
def get_document_asset(task_id: str, filename: str) -> FileResponse:
    payload = store.get(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail="任务不存在或已过期。")
    asset = next(
        (item for item in payload.get("assets", []) if item.get("filename") == filename),
        None,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="图片不存在。")
    path = store.task_dir(task_id) / "assets" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片文件不存在或已清理。")
    return FileResponse(path)


@app.post("/api/documents/{task_id}/process", response_model=DocumentResponse)
def process(task_id: str, request: ProcessRequest) -> dict:
    try:
        return process_document(
            task_id,
            finding_ids=request.finding_ids,
            improve_structure=request.improve_structure,
            ai_config=request.ai_config,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在或已过期。") from exc


    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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

