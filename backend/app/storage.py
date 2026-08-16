from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .config import settings
from .database import connection, document_to_row, row_to_document

UTC = timezone.utc


class TaskStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = Lock()
        self.root.mkdir(parents=True, exist_ok=True)

    def task_dir(self, task_id: str) -> Path:
        return self.root / task_id

    def create(self, task_id: str, payload: dict[str, Any], user_id: int | None = None) -> None:
        with self._lock:
            directory = self.task_dir(task_id)
            directory.mkdir(parents=True, exist_ok=False)
            payload["created_at"] = datetime.now(UTC).isoformat()
            self._write(directory / "document.json", payload)
            if user_id is not None:
                self.upsert_document(payload, user_id)

    def get(self, task_id: str) -> dict[str, Any] | None:
        path = self.task_dir(task_id) / "document.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, task_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            path = self.task_dir(task_id) / "document.json"
            if not path.exists():
                raise FileNotFoundError(task_id)
            payload.setdefault("created_at", datetime.now(UTC).isoformat())
            self._write(path, payload)
            user_id = payload.get("user_id")
            if user_id:
                self.upsert_document(payload, int(user_id))

    def upsert_document(self, payload: dict[str, Any], user_id: int) -> None:
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO documents (
                        id, user_id, filename, source_type, status, progress_percent,
                        progress_message, original_content, processed_content, stats_json,
                        findings_json, warnings_json, assets_json, error_message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        filename = VALUES(filename),
                        source_type = VALUES(source_type),
                        status = VALUES(status),
                        progress_percent = VALUES(progress_percent),
                        progress_message = VALUES(progress_message),
                        original_content = VALUES(original_content),
                        processed_content = VALUES(processed_content),
                        stats_json = VALUES(stats_json),
                        findings_json = VALUES(findings_json),
                        warnings_json = VALUES(warnings_json),
                        assets_json = VALUES(assets_json),
                        error_message = VALUES(error_message),
                        completed_at = CASE
                            WHEN VALUES(status) IN ('processed', 'failed') THEN CURRENT_TIMESTAMP
                            ELSE completed_at
                        END
                    """,
                    document_to_row(payload, user_id),
                )

    def record_progress(self, task_id: str, status: str, percent: int, message: str) -> None:
        payload = self.get(task_id)
        if not payload:
            raise FileNotFoundError(task_id)
        payload["status"] = status
        payload["progress_percent"] = max(0, min(100, int(percent)))
        payload["progress_message"] = message
        self.update(task_id, payload)
        user_id = int(payload["user_id"])
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO document_progress_events
                        (document_id, user_id, status, progress_percent, message)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (task_id, user_id, status, payload["progress_percent"], message),
                )

    def list_documents(self, user_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with connection() as conn:
            with conn.cursor() as cursor:
                if user_id is None:
                    cursor.execute(
                        """
                        SELECT d.*, u.username
                        FROM documents d
                        JOIN users u ON u.id = d.user_id
                        ORDER BY d.created_at DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT d.*, u.username
                        FROM documents d
                        JOIN users u ON u.id = d.user_id
                        WHERE d.user_id = %s
                        ORDER BY d.created_at DESC
                        LIMIT %s
                        """,
                        (user_id, limit),
                    )
                return [row_to_document(row) for row in cursor.fetchall()]

    def get_document(self, task_id: str) -> dict[str, Any] | None:
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.*, u.username
                    FROM documents d
                    JOIN users u ON u.id = d.user_id
                    WHERE d.id = %s
                    """,
                    (task_id,),
                )
                row = cursor.fetchone()
                return row_to_document(row) if row else None

    def save_asset(self, task_id: str, filename: str, content: bytes) -> Path:
        directory = self.task_dir(task_id) / "assets"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_bytes(content)
        return path

    def cleanup_expired(self) -> int:
        threshold = datetime.now(UTC) - timedelta(minutes=settings.task_ttl_minutes)
        removed = 0
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            metadata = directory / "document.json"
            modified = datetime.fromtimestamp(directory.stat().st_mtime, tz=UTC)
            if metadata.exists():
                try:
                    created = json.loads(metadata.read_text(encoding="utf-8")).get(
                        "created_at"
                    )
                    if created:
                        modified = datetime.fromisoformat(created)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            if modified < threshold:
                shutil.rmtree(directory, ignore_errors=True)
                removed += 1
        return removed

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)


store = TaskStore(settings.temp_dir)
