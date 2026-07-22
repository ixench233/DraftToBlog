from __future__ import annotations

import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from qcloud_cos import CosConfig, CosS3Client

from ..config import settings

UTC = timezone.utc


class MediaServiceError(RuntimeError):
    pass


def upload_task_assets(task_id: str, assets: list[dict]) -> list[dict]:
    pending = [asset for asset in assets if asset.get("status") != "uploaded"]
    if not pending:
        return assets
    with ThreadPoolExecutor(max_workers=min(6, len(pending))) as executor:
        list(executor.map(lambda asset: _upload_one_asset(task_id, asset), pending))
    return assets


def _upload_one_asset(task_id: str, asset: dict) -> None:
    try:
        if asset.get("status") == "uploaded":
            return
        path = settings.temp_dir / task_id / asset["local_path"]
        try:
            if settings.cos_ready:
                asset["url"] = _upload_cos(path)
                asset["provider"] = "cos"
            elif settings.picgo_ready:
                asset["url"] = _upload_picgo(path)
                asset["provider"] = "picgo"
            else:
                raise MediaServiceError("PicGo 和腾讯云 COS 均未完整配置。")
            asset["status"] = "uploaded"
            asset["error"] = ""
        except Exception as upload_error:
            if settings.picgo_ready and asset.get("provider") != "picgo":
                try:
                    asset["url"] = _upload_picgo(path)
                    asset["provider"] = "picgo"
                    asset["status"] = "uploaded"
                    asset["error"] = ""
                    return
                except Exception as picgo_error:
                    upload_error = picgo_error
            asset["status"] = "failed"
            asset["error"] = str(upload_error)[:300]
    except Exception as exc:
        asset["status"] = "failed"
        asset["error"] = str(exc)[:300]


def append_uploaded_assets(text: str, assets: list[dict]) -> str:
    uploaded = [item for item in assets if item.get("status") == "uploaded" and item.get("url")]
    if not uploaded:
        return text
    references = "\n".join(f"![{Path(item['filename']).stem}]({item['url']})" for item in uploaded)
    return f"{text.rstrip()}\n\n## 文档图片\n\n{references}\n"


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
        raise MediaServiceError("找不到 PicGo 可执行文件。")
    command = [executable, "--config", config_path, "upload", "--format", "json", str(path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False, shell=False)
    finally:
        if temporary_config:
            Path(temporary_config).unlink(missing_ok=True)
    if result.returncode != 0:
        raise MediaServiceError("PicGo 上传失败：" + (result.stderr.strip() or result.stdout.strip())[-300:])
    try:
        data = json.loads(result.stdout.strip())
        url = _find_url(data)
        if url:
            return url
    except json.JSONDecodeError:
        pass
    match = re.search(r"https?://[^\s\"']+", result.stdout)
    if match:
        return match.group(0)
    raise MediaServiceError("PicGo 未返回图片 URL。")


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


def _cos_client() -> CosS3Client:
    config = CosConfig(Region=settings.cos_region, SecretId=settings.cos_secret_id, SecretKey=settings.cos_secret_key)
    return CosS3Client(config)
