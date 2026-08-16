from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from .config import settings
from .auth import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, create_session_token, parse_session_token, verify_password
from .database import get_user_by_id, get_user_by_username, init_database
from .schemas import ConfigStatus, CurrentUser, DocumentResponse, LoginRequest, ProcessRequest
from .services.ai_service import AIServiceError
from .services.document_service import analyze_upload, create_demo, process_document
from .services.export_service import export_document
from .services.media_service import cleanup_expired_cos_objects, diagnose_upload_chain
from .storage import store

_schema_ready = False
_schema_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema()
    store.cleanup_expired()
    threading.Thread(target=_cleanup_cos_safely, daemon=True).start()
    yield


def _cleanup_cos_safely() -> None:
    try:
        cleanup_expired_cos_objects()
    except Exception:
        # A storage outage must not prevent the API from starting.
        pass


def get_current_user(
    dtb_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> CurrentUser:
    ensure_schema()
    payload = parse_session_token(dtb_session or "")
    if not payload:
        raise HTTPException(status_code=401, detail="Please sign in.")
    row = get_user_by_id(int(payload["id"]))
    if row is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return CurrentUser(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
    )


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if not _schema_ready:
            init_database()
            _schema_ready = True


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can access all users' history.")
    return user


def assert_document_access(payload: dict, user: CurrentUser) -> None:
    if payload.get("user_id") != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="You can only access your own documents.")


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


@app.get("/api/config/upload-diagnostics")
def upload_diagnostics() -> dict[str, object]:
    return diagnose_upload_chain()


@app.post("/api/auth/login", response_model=CurrentUser)
def login(request: LoginRequest) -> Response:
    ensure_schema()
    user = get_user_by_username(request.username.strip())
    if user is None or not verify_password(request.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    current = CurrentUser(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        role=user["role"],
    )
    response = Response(
        content=current.model_dump_json(),
        media_type="application/json",
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/api/auth/logout")
def logout() -> dict[str, str]:
    response = Response(content='{"status":"ok"}', media_type="application/json")
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.get("/api/users/me", response_model=CurrentUser)
def current_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user


@app.get("/api/documents/history", response_model=list[DocumentResponse])
def document_history(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return store.list_documents(user_id=user.id)


@app.get("/api/admin/documents", response_model=list[DocumentResponse])
def admin_document_history(_: CurrentUser = Depends(require_admin)) -> list[dict]:
    return store.list_documents(user_id=None)


@app.post("/api/documents/analyze", response_model=DocumentResponse)
async def analyze_document(file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)) -> dict:
    filename = file.filename or "document"
    limit_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read(limit_bytes + 1) if limit_bytes > 0 else await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty.")
    if limit_bytes > 0 and len(content) > limit_bytes:
        raise HTTPException(status_code=413, detail=f"File cannot exceed {settings.max_upload_mb} MB.")
    try:
        return analyze_upload(filename, content, user_id=user.id, username=user.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/documents/demo", response_model=DocumentResponse)
def demo_document(user: CurrentUser = Depends(get_current_user)) -> dict:
    return create_demo(user_id=user.id, username=user.username)


@app.get("/api/documents/{task_id}", response_model=DocumentResponse)
def get_document(task_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    payload = store.get_document(task_id) or store.get(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Document task does not exist or has expired.")
    assert_document_access(payload, user)
    return payload


@app.get("/api/documents/{task_id}/assets/{filename}")
def get_document_asset(task_id: str, filename: str, user: CurrentUser = Depends(get_current_user)) -> FileResponse:
    payload = store.get_document(task_id) or store.get(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Document task does not exist or has expired.")
    assert_document_access(payload, user)
    asset = next(
        (item for item in payload.get("assets", []) if item.get("filename") == filename),
        None,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Image does not exist.")
    path = store.task_dir(task_id) / "assets" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file does not exist or has been cleaned up.")
    return FileResponse(path)


@app.post("/api/documents/{task_id}/process", response_model=DocumentResponse)
def process(
    task_id: str,
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    x_dtb_async: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    payload = store.get(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Document task does not exist or has expired.")
    assert_document_access(payload, user)
    if payload.get("status") == "processing":
        return payload
    if x_dtb_async != "true":
        try:
            return process_document(
                task_id,
                finding_ids=request.finding_ids,
                improve_structure=request.improve_structure,
                ai_config=request.ai_config,
                progress_callback=lambda percent, message: store.record_progress(task_id, "processing", percent, message),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document task does not exist or has expired.") from exc
        except AIServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    store.record_progress(task_id, "processing", 30, "Generation started.")
    background_tasks.add_task(
        _process_document_background,
        task_id,
        request.finding_ids,
        request.improve_structure,
        request.ai_config,
    )
    return store.get(task_id) or payload


def _process_document_background(
    task_id: str,
    finding_ids: list[str],
    improve_structure: bool,
    ai_config: object | None,
) -> None:
    try:
        process_document(
            task_id,
            finding_ids=finding_ids,
            improve_structure=improve_structure,
            ai_config=ai_config,
            progress_callback=lambda percent, message: store.record_progress(task_id, "processing", percent, message),
        )
        store.record_progress(task_id, "processed", 100, "Generation completed.")
    except FileNotFoundError:
        return
    except AIServiceError as exc:
        _mark_task_failed(task_id, str(exc))
    except Exception as exc:
        _mark_task_failed(task_id, str(exc))


def _mark_task_failed(task_id: str, message: str) -> None:
    payload = store.get(task_id)
    if not payload:
        return
    payload["status"] = "failed"
    payload["progress_percent"] = 100
    payload["progress_message"] = "Generation failed."
    payload["error_message"] = message
    store.update(task_id, payload)
    store.record_progress(task_id, "failed", 100, "Generation failed.")


@app.get("/api/documents/{task_id}/export/{format_name}")
def export(task_id: str, format_name: str, user: CurrentUser = Depends(get_current_user)) -> Response:
    payload = store.get_document(task_id) or store.get(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Document task does not exist or has expired.")
    assert_document_access(payload, user)
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
