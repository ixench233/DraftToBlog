from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .config import settings

UTC = timezone.utc


class TaskStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = Lock()
        self.root.mkdir(parents=True, exist_ok=True)

    def task_dir(self, task_id: str) -> Path:
        return self.root / task_id

    def create(self, task_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            directory = self.task_dir(task_id)
            directory.mkdir(parents=True, exist_ok=False)
            payload["created_at"] = datetime.now(UTC).isoformat()
            self._write(directory / "document.json", payload)

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
