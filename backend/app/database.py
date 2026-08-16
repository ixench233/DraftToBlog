from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from .auth import hash_password
from .config import settings

UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connection(database: str | None = None, use_default_database: bool = True) -> Iterator[Connection]:
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=database if database is not None else (settings.mysql_database if use_default_database else None),
        charset="utf8mb4",
        autocommit=False,
        cursorclass=DictCursor,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database() -> None:
    with connection(use_default_database=False) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )

    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(80) NOT NULL UNIQUE,
                    display_name VARCHAR(120) NOT NULL,
                    role ENUM('user', 'admin') NOT NULL DEFAULT 'user',
                    password_hash VARCHAR(255) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute("SHOW COLUMNS FROM users LIKE 'password_hash'")
            if cursor.fetchone() is None:
                cursor.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NOT NULL DEFAULT '' AFTER role")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id CHAR(32) NOT NULL PRIMARY KEY,
                    user_id BIGINT UNSIGNED NOT NULL,
                    filename VARCHAR(255) NOT NULL,
                    source_type ENUM('markdown', 'docx', 'pdf') NOT NULL,
                    status ENUM('ready', 'processing', 'processed', 'failed') NOT NULL DEFAULT 'ready',
                    progress_percent TINYINT UNSIGNED NOT NULL DEFAULT 0,
                    progress_message VARCHAR(255) NOT NULL DEFAULT '',
                    original_content MEDIUMTEXT NOT NULL,
                    processed_content MEDIUMTEXT NOT NULL,
                    stats_json JSON NOT NULL,
                    findings_json JSON NOT NULL,
                    warnings_json JSON NOT NULL,
                    assets_json JSON NOT NULL,
                    error_message TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    completed_at DATETIME NULL,
                    CONSTRAINT fk_documents_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    INDEX idx_documents_user_created (user_id, created_at),
                    INDEX idx_documents_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS document_progress_events (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    document_id CHAR(32) NOT NULL,
                    user_id BIGINT UNSIGNED NOT NULL,
                    status ENUM('ready', 'processing', 'processed', 'failed') NOT NULL,
                    progress_percent TINYINT UNSIGNED NOT NULL,
                    message VARCHAR(255) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT fk_progress_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
                    CONSTRAINT fk_progress_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    INDEX idx_progress_document_created (document_id, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            ensure_user(settings.default_user_name, settings.default_user_display_name, "user", settings.default_user_password, conn=conn)
            ensure_user(settings.default_admin_name, settings.default_admin_display_name, "admin", settings.default_admin_password, conn=conn)


def ensure_user(username: str, display_name: str, role: str, password: str | None = None, conn: Connection | None = None) -> dict[str, Any]:
    owns_connection = conn is None
    ctx = connection() if conn is None else None
    active = conn
    if ctx is not None:
        active = ctx.__enter__()
    try:
        assert active is not None
        with active.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (username, display_name, role, password_hash)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    display_name = VALUES(display_name),
                    role = VALUES(role),
                    password_hash = IF(password_hash = '', VALUES(password_hash), password_hash)
                """,
                (username, display_name, role, hash_password(password or "123456")),
            )
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Failed to create user.")
            return row
    finally:
        if ctx is not None:
            ctx.__exit__(None, None, None)
        elif owns_connection:
            pass


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            return cursor.fetchone()


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return cursor.fetchone()


def document_to_row(payload: dict[str, Any], user_id: int) -> tuple[Any, ...]:
    return (
        payload["id"],
        user_id,
        payload["filename"],
        payload["source_type"],
        payload.get("status", "ready"),
        int(payload.get("progress_percent", 0)),
        payload.get("progress_message", ""),
        payload["original_content"],
        payload["processed_content"],
        json.dumps(payload["stats"], ensure_ascii=False),
        json.dumps(payload["findings"], ensure_ascii=False),
        json.dumps(payload.get("warnings", []), ensure_ascii=False),
        json.dumps(payload.get("assets", []), ensure_ascii=False),
        payload.get("error_message"),
    )


def row_to_document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": row.get("username", ""),
        "filename": row["filename"],
        "source_type": row["source_type"],
        "status": row["status"],
        "progress_percent": row["progress_percent"],
        "progress_message": row["progress_message"],
        "original_content": row["original_content"],
        "processed_content": row["processed_content"],
        "stats": _json(row["stats_json"], {}),
        "findings": _json(row["findings_json"], []),
        "warnings": _json(row["warnings_json"], []),
        "assets": _json(row["assets_json"], []),
        "error_message": row.get("error_message") or "",
        "created_at": _dt(row.get("created_at")),
        "updated_at": _dt(row.get("updated_at")),
        "completed_at": _dt(row.get("completed_at")),
    }


def _json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _dt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat()
    return str(value)
