from __future__ import annotations

import json
import logging
import mimetypes
import re
import shutil
import shlex
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
import paramiko
from qcloud_cos import CosConfig, CosS3Client

from ..config import settings


logger = logging.getLogger(__name__)


class MediaServiceError(RuntimeError):
    pass


UPLOAD_ATTEMPTS = 4
UPLOAD_RETRY_BASE_DELAY_SECONDS = 1.0
DEFAULT_UPLOAD_WORKERS = 2


def upload_task_assets(task_id: str, assets: list[dict]) -> list[dict]:
    pending = [asset for asset in assets if asset.get("status") != "uploaded"]
    if not pending:
        return assets
    max_workers = max(1, min(_upload_worker_count(), len(pending)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(lambda asset: _upload_one_asset(task_id, asset), pending))
    return assets


def diagnose_upload_chain() -> dict[str, object]:
    diagnostics: dict[str, object] = {
        "upload_provider": settings.upload_provider,
        "remote_upload_ready": _remote_upload_ready(),
        "remote_upload_host": settings.deploy_host,
        "cos_ready": settings.cos_ready,
        "picgo_ready": settings.picgo_ready,
        "picgo_bucket": _picgo_bucket_name() if settings.cos_bucket else "",
        "picgo_app_id_configured": bool(_picgo_app_id()),
        "public_base_url": settings.cos_public_base_url,
        "provider_order": _upload_provider_order(),
        "effective_provider_order": _upload_provider_order(),
        "public_base_available": None,
        "public_base_status": None,
        "public_base_error": "",
        "cos_endpoint_available": None,
        "cos_endpoint_error": "",
    }
    if settings.cos_public_base_url:
        try:
            response = httpx.head(
                settings.cos_public_base_url.rstrip("/") + "/",
                timeout=10,
                follow_redirects=True,
            )
            diagnostics["public_base_available"] = response.status_code < 500
            diagnostics["public_base_status"] = response.status_code
        except httpx.HTTPError as exc:
            diagnostics["public_base_available"] = False
            diagnostics["public_base_error"] = str(exc)[:300]
    if settings.cos_ready:
        try:
            _cos_client().list_objects(Bucket=settings.cos_bucket, Prefix=settings.cos_path_prefix, MaxKeys=1)
            diagnostics["cos_endpoint_available"] = True
        except Exception as exc:
            diagnostics["cos_endpoint_available"] = False
            diagnostics["cos_endpoint_error"] = str(exc)[:300]
    return diagnostics


def append_uploaded_assets(text: str, assets: list[dict]) -> str:
    uploaded = [item for item in assets if item.get("status") == "uploaded" and item.get("url")]
    if not uploaded:
        return text
    references = "\n".join(f"![{Path(item['filename']).stem}]({item['url']})" for item in uploaded)
    return f"{text.rstrip()}\n\n## Document Images\n\n{references}\n"


def cleanup_expired_cos_objects() -> int:
    if not settings.cos_ready or settings.cos_auto_delete_days <= 0:
        return 0
    client = _cos_client()
    prefix = settings.cos_path_prefix.strip("/") + "/"
    threshold = datetime.now(UTC) - timedelta(days=settings.cos_auto_delete_days)
    deleted = 0
    marker = ""
    while True:
        response = client.list_objects(Bucket=settings.cos_bucket, Prefix=prefix, Marker=marker, MaxKeys=1000)
        for item in response.get("Contents", []):
            modified = datetime.fromisoformat(item["LastModified"].replace("Z", "+00:00"))
            if modified < threshold:
                client.delete_object(Bucket=settings.cos_bucket, Key=item["Key"])
                deleted += 1
        if response.get("IsTruncated") not in {True, "true", "True"}:
            break
        marker = response.get("NextMarker", "")
        if not marker:
            break
    return deleted


def _upload_one_asset(task_id: str, asset: dict) -> None:
    try:
        if asset.get("status") == "uploaded":
            return
        path = settings.temp_dir / task_id / asset["local_path"]
        upload_error: Exception | None = None
        for provider in _upload_provider_order():
            try:
                asset["url"] = _upload_with_provider_with_retries(provider, path)
                asset["provider"] = provider
                if provider != "remote":
                    _ensure_public_url_available(asset["url"])
                asset["status"] = "uploaded"
                asset["error"] = ""
                return
            except Exception as exc:
                upload_error = exc
        raise upload_error or MediaServiceError("No configured upload provider is available.")
    except Exception as exc:
        asset["status"] = "failed"
        asset["error"] = str(exc)[:300]


def _upload_provider_order() -> list[str]:
    provider = getattr(settings, "upload_provider", "auto")
    if provider == "remote":
        if not _remote_upload_ready():
            raise MediaServiceError("Remote upload is not configured.")
        return ["remote"]
    if provider == "picgo":
        if not settings.picgo_ready:
            raise MediaServiceError("PicGo is not configured.")
        return ["picgo"]
    if provider == "cos":
        if not settings.cos_ready:
            raise MediaServiceError("Tencent COS is not fully configured.")
        return ["cos"]
    if provider != "auto":
        raise MediaServiceError(f"Unsupported upload provider: {provider}")

    order: list[str] = []
    if _remote_upload_ready():
        order.append("remote")
    if settings.cos_ready:
        order.append("cos")
    if settings.picgo_ready:
        order.append("picgo")
    if not order:
        raise MediaServiceError("Neither Tencent COS nor PicGo is configured.")
    return order


def _upload_with_provider(provider: str, path: Path) -> str:
    if provider == "remote":
        return _upload_remote_picgo(path)
    if provider == "cos":
        return _upload_cos(path)
    if provider == "picgo":
        return _upload_picgo(path)
    raise MediaServiceError(f"Unsupported upload provider: {provider}")


def _remote_upload_ready() -> bool:
    return bool(getattr(settings, "remote_upload_ready", False))


def _upload_remote_picgo(path: Path) -> str:
    client = _remote_ssh_client()
    sftp = None
    remote_dir = f"/tmp/draft-to-blog-upload-{uuid.uuid4().hex}"
    remote_path = f"{remote_dir}/{path.name}"
    remote_config = f"{remote_dir}/picgo-config.json"
    try:
        sftp = client.open_sftp()
        _remote_exec(client, f"mkdir -p {shlex.quote(remote_dir)}")
        sftp.put(str(path), remote_path)
        with sftp.file(remote_config, "w") as handle:
            handle.write(json.dumps(_picgo_cos_config(), ensure_ascii=False))

        stdout, stderr, return_code = _remote_exec(
            client,
            " ".join(
                [
                    shlex.quote(settings.picgo_bin or "picgo"),
                    "--config",
                    shlex.quote(remote_config),
                    "upload",
                    "--format",
                    "json",
                    shlex.quote(remote_path),
                ]
            ),
            timeout=120,
            check=False,
        )
        if return_code != 0:
            raise MediaServiceError("Remote PicGo upload failed: " + (stderr.strip() or stdout.strip())[-300:])
        url = ""
        try:
            url = _find_url(json.loads(stdout.strip())) if stdout.strip().startswith(("{", "[")) else ""
        except json.JSONDecodeError:
            url = ""
        if not url:
            match = re.search(r"https?://[^\s\"']+", stdout)
            url = match.group(0) if match else ""
        if not url:
            raise MediaServiceError("Remote PicGo did not return an image URL.")
        url = _normalize_public_url(url)
        _ensure_remote_public_url_available(client, url)
        return url
    finally:
        try:
            _remote_exec(client, f"rm -rf {shlex.quote(remote_dir)}", check=False)
        finally:
            if sftp:
                sftp.close()
            client.close()


def _remote_ssh_client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_args: dict[str, object] = {
        "hostname": settings.deploy_host,
        "port": settings.deploy_port,
        "username": settings.deploy_user,
        "timeout": 15,
        "banner_timeout": 15,
        "auth_timeout": 15,
    }
    if settings.deploy_ssh_key_path:
        connect_args["key_filename"] = settings.deploy_ssh_key_path
    if settings.deploy_password:
        connect_args["password"] = settings.deploy_password
    client.connect(**connect_args)
    return client


def _remote_exec(
    client: paramiko.SSHClient,
    command: str,
    *,
    timeout: int = 60,
    check: bool = True,
) -> tuple[str, str, int]:
    _, stdout_stream, stderr_stream = client.exec_command(command, timeout=timeout)
    stdout = stdout_stream.read().decode("utf-8", "replace")
    stderr = stderr_stream.read().decode("utf-8", "replace")
    return_code = stdout_stream.channel.recv_exit_status()
    if check and return_code != 0:
        raise MediaServiceError((stderr.strip() or stdout.strip() or f"Remote command failed: {command}")[-300:])
    return stdout, stderr, return_code


def _ensure_remote_public_url_available(client: paramiko.SSHClient, url: str) -> None:
    stdout, stderr, return_code = _remote_exec(
        client,
        f"curl -I -L --max-time 30 {shlex.quote(url)}",
        timeout=45,
        check=False,
    )
    status_lines = [line for line in stdout.splitlines() if line.upper().startswith("HTTP/")]
    status_line = status_lines[-1] if status_lines else ""
    if return_code != 0 or not re.search(r"\s2\d\d\s", status_line):
        raise MediaServiceError("Remote public URL check failed: " + (stderr.strip() or stdout.strip())[-300:])
    if "content-type: image/" not in stdout.lower():
        raise MediaServiceError("Remote public URL did not return an image content type.")


def _picgo_cos_config() -> dict:
    return {
        "picBed": {
            "uploader": "tcyun",
            "current": "tcyun",
            "tcyun": {
                "secretId": settings.cos_secret_id,
                "secretKey": settings.cos_secret_key,
                "bucket": settings.cos_bucket,
                "appId": "",
                "area": settings.cos_region,
                "path": settings.cos_path_prefix.strip("/") + "/",
                "customUrl": settings.cos_public_base_url.rstrip("/"),
                "version": "v5",
            },
        }
    }


def _upload_with_provider_with_retries(provider: str, path: Path) -> str:
    last_error: Exception | None = None
    for attempt in range(UPLOAD_ATTEMPTS):
        try:
            return _upload_with_provider(provider, path)
        except Exception as exc:
            last_error = exc
            if attempt < UPLOAD_ATTEMPTS - 1:
                logger.warning(
                    "Image upload failed; retrying. provider=%s attempt=%s/%s file=%s error=%s",
                    provider,
                    attempt + 1,
                    UPLOAD_ATTEMPTS,
                    path.name,
                    str(exc)[:200],
                )
                time.sleep(UPLOAD_RETRY_BASE_DELAY_SECONDS * (2**attempt))
                continue
            raise MediaServiceError(f"{provider} upload failed after {UPLOAD_ATTEMPTS} attempts: {exc}") from exc
    raise last_error or MediaServiceError(f"{provider} upload failed.")


def _upload_worker_count() -> int:
    raw_value = getattr(settings, "cos_upload_workers", DEFAULT_UPLOAD_WORKERS)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_UPLOAD_WORKERS


def _upload_picgo(path: Path) -> str:
    config_path = settings.picgo_config_path
    temporary_config: str | None = None
    if settings.cos_ready:
        try:
            source = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            source = {}
        pic_bed = source.setdefault("picBed", {})
        pic_bed["uploader"] = "tcyun"
        pic_bed["current"] = "tcyun"
        pic_bed["tcyun"] = {
            "secretId": settings.cos_secret_id,
            "secretKey": settings.cos_secret_key,
            "bucket": settings.cos_bucket,
            "appId": "",
            "area": settings.cos_region,
            "path": settings.cos_path_prefix.strip("/") + "/",
            "customUrl": settings.cos_public_base_url.rstrip("/"),
            "version": "v5",
        }
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False)
        with handle:
            json.dump(source, handle, ensure_ascii=False)
        temporary_config = handle.name
        config_path = temporary_config

    executable = shutil.which(settings.picgo_bin)
    if not executable:
        raise MediaServiceError("PicGo executable was not found.")
    upload_path = _unique_picgo_upload_path(path)
    command = [executable, "--config", config_path, "upload", "--format", "json", str(upload_path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False, shell=False)
    finally:
        if upload_path != path:
            upload_path.unlink(missing_ok=True)
        if temporary_config:
            Path(temporary_config).unlink(missing_ok=True)
    if result.returncode != 0:
        raise MediaServiceError("PicGo upload failed: " + (result.stderr.strip() or result.stdout.strip())[-300:])
    try:
        data = json.loads(result.stdout.strip())
        url = _find_url(data)
        if url:
            return _normalize_public_url(url)
    except json.JSONDecodeError:
        pass
    match = re.search(r"https?://[^\s\"']+", result.stdout)
    if match:
        return _normalize_public_url(match.group(0))
    raise MediaServiceError("PicGo did not return an image URL.")


def _find_url(value: object) -> str:
    if isinstance(value, str):
        return value if value.startswith(("http://", "https://")) else ""
    if isinstance(value, list):
        return next((url for item in value if (url := _find_url(item))), "")
    if isinstance(value, dict):
        for key in ("imgUrl", "url", "result", "urls", "data"):
            if key in value and (url := _find_url(value[key])):
                return url
        return next((url for item in value.values() if (url := _find_url(item))), "")
    return ""


def _upload_cos(path: Path) -> str:
    suffix = path.suffix.lower() or ".bin"
    key = f"{settings.cos_path_prefix.strip('/')}/{datetime.now(UTC):%Y/%m}/{uuid.uuid4().hex}{suffix}"
    _cos_client().put_object(
        Bucket=settings.cos_bucket,
        Key=key,
        Body=path.read_bytes(),
        ContentType=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )
    return f"{settings.cos_public_base_url.rstrip('/')}/{quote(key, safe='/')}"


def _ensure_public_url_available(url: str) -> None:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = httpx.head(url, timeout=15, follow_redirects=True)
            if response.status_code in {405, 501}:
                response = httpx.get(
                    url,
                    headers={"Range": "bytes=0-0"},
                    timeout=15,
                    follow_redirects=True,
                )
            response.raise_for_status()
            break
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(0.5 * (2**attempt))
                continue
            raise MediaServiceError(f"Image was uploaded but public URL is not reachable: {url}; {exc}") from exc
    else:
        raise MediaServiceError(f"Image was uploaded but public URL is not reachable: {url}; {last_error}")
    content_type = response.headers.get("content-type", "")
    if content_type and not content_type.lower().startswith("image/"):
        raise MediaServiceError(f"Image public URL did not return an image content type: {content_type}")


def _normalize_public_url(url: str) -> str:
    if settings.cos_public_base_url and settings.cos_path_prefix.strip("/") in url:
        public_base = settings.cos_public_base_url.rstrip("/")
        path_prefix = "/" + settings.cos_path_prefix.strip("/") + "/"
        if path_prefix in url:
            return public_base + path_prefix + url.split(path_prefix, 1)[1]
    if settings.cos_public_base_url and url.startswith("http://"):
        public_base = settings.cos_public_base_url.rstrip("/")
        host = re.sub(r"^https?://", "", public_base).split("/", 1)[0]
        if host and host in url:
            return "https://" + url.split("://", 1)[1]
    return url


def _unique_picgo_upload_path(path: Path) -> Path:
    unique = path.with_name(f"{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex}{path.suffix.lower() or '.bin'}")
    shutil.copy2(path, unique)
    return unique


def _picgo_bucket_name() -> str:
    return settings.cos_bucket


def _picgo_bucket_base_name() -> str:
    app_id = _picgo_app_id()
    suffix = f"-{app_id}"
    if app_id and settings.cos_bucket.endswith(suffix):
        return settings.cos_bucket[: -len(suffix)]
    return settings.cos_bucket


def _picgo_app_id() -> str:
    match = re.match(r"^(.+)-(\d+)$", settings.cos_bucket)
    return match.group(2) if match else ""


def _cos_client() -> CosS3Client:
    config = CosConfig(
        Region=settings.cos_region,
        SecretId=settings.cos_secret_id,
        SecretKey=settings.cos_secret_key,
        Timeout=30,
        KeepAlive=False,
        PoolConnections=max(1, _upload_worker_count()),
        PoolMaxSize=max(1, _upload_worker_count()),
        AutoSwitchDomainOnRetry=True,
    )
    return CosS3Client(config)
