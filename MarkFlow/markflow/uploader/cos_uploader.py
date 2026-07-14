from __future__ import annotations
import io
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from qcloud_cos import CosConfig, CosS3Client

from markflow.config import AppConfig
from markflow.models import ImageBlock


def _safe_filename(stem: str) -> str:
    """Convert any filename to ASCII-safe form: keep alphanumerics, replace rest with '-'."""
    # Replace non-ASCII and non-safe chars so the COS key & URL need no encoding
    safe = re.sub(r"[^\w\-]", "-", stem, flags=re.ASCII)
    safe = re.sub(r"-{2,}", "-", safe).strip("-") or "img"
    return safe


class CosUploader:
    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._cos = cfg.cos
        self._client: CosS3Client | None = None
        self._init_client()

    def _init_client(self) -> None:
        c = self._cos
        if not (c.secret_id and c.secret_key and c.bucket and c.region):
            return
        config = CosConfig(
            Region=c.region,
            SecretId=c.secret_id,
            SecretKey=c.secret_key,
        )
        self._client = CosS3Client(config)

    def is_ready(self) -> bool:
        return self._client is not None

    def upload(self, img: ImageBlock, source_name: str) -> str:
        """Upload image bytes to COS and return the public URL. Returns "" on failure."""
        if not self._client:
            return ""

        now = datetime.now()
        # Use hash-only filename to guarantee the COS key and URL are pure ASCII
        hash8 = img.md5[:8]
        key_path = self._cos.path.strip("/")
        key = f"{key_path}/{now.year}/{now.month:02d}/{hash8}.{img.ext}"

        try:
            self._client.put_object(
                Bucket=self._cos.bucket,
                Body=io.BytesIO(img.data),
                Key=key,
                ContentType=f"image/{img.ext if img.ext != 'jpg' else 'jpeg'}",
                ACL="public-read",
            )
        except Exception as e:
            raise RuntimeError(f"COS upload failed for {key}: {e}") from e

        return self._build_url(key)

    def _build_url(self, key: str) -> str:
        cdn = (self._cfg.cdn_domain or self._cos.custom_url or "").rstrip("/")
        base = cdn or (
            f"https://{self._cos.bucket}.cos.{self._cos.region}.myqcloud.com"
        )
        # key is already ASCII-safe; encode just in case
        encoded_key = quote(key, safe="/")
        return f"{base}/{encoded_key}"
