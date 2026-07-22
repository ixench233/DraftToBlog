from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Lock
from urllib.parse import urlparse

import httpx

from ..config import settings


class AIServiceError(RuntimeError):
    """A safe, user-facing AI service error."""


@dataclass(frozen=True)
class AIConnection:
    base_url: str
    api_key: str
    model: str
    uses_official_quota: bool = False


class _DailyQuota:
    def __init__(self) -> None:
        self._lock = Lock()
        self._day = date.today()
        self._count = 0

    def consume(self, limit: int) -> None:
        with self._lock:
            today = date.today()
            if today != self._day:
                self._day = today
                self._count = 0
            if limit > 0 and self._count >= limit:
                raise AIServiceError("今日服务器 AI 调用次数已达上限，请明天再试或使用会话 API 配置。")
            self._count += 1


_quota = _DailyQuota()


def resolve_connection(user_config: object | None = None) -> AIConnection | None:
    if user_config is not None and settings.allow_user_ai_config:
        connection = AIConnection(
            base_url=str(getattr(user_config, "base_url", "")).strip(),
            api_key=str(getattr(user_config, "api_key", "")).strip(),
            model=str(getattr(user_config, "model", "")).strip(),
        )
        _validate_connection(connection)
        return connection
    if settings.official_ai_ready:
        connection = AIConnection(
            base_url=settings.official_ai_base_url.strip(),
            api_key=settings.official_ai_api_key.strip(),
            model=settings.official_ai_model.strip(),
            uses_official_quota=True,
        )
        _validate_connection(connection)
        return connection
    return None


def improve_article(text: str, filename: str, connection: AIConnection) -> str:
    chunks = _split_markdown(text, 1200)
    if len(chunks) == 1:
        return _improve_article_chunk(chunks[0], filename, connection)
    with ThreadPoolExecutor(max_workers=min(3, len(chunks))) as executor:
        parts = list(
            executor.map(
                lambda item: _improve_article_chunk(
                    item[1], f"{filename} (part {item[0] + 1})", connection
                ),
                enumerate(chunks),
            )
        )
    return "\n\n".join(parts)


def _improve_article_chunk(text: str, filename: str, connection: AIConnection) -> str:
    if len(text) > settings.official_ai_max_input_chars:
        raise AIServiceError(f"文章长度超过 AI 单次处理上限（{settings.official_ai_max_input_chars} 字符）。")
    if connection.uses_official_quota:
        _quota.consume(settings.official_ai_daily_request_limit)

    prompt = (
        "请将下面的草稿整理成可直接发布的 Markdown 文章。\n"
        "要求：保留所有事实、数字、链接、代码块、表格和图片引用；不要虚构信息；"
        "优化标题层级、段落结构、表达和可读性；不要输出解释或代码围栏，只输出文章正文。\n\n"
        f"文件名：{filename}\n\n草稿：\n{text}"
    )
    try:
        response = httpx.post(
            f"{connection.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {connection.api_key}"},
            json={
                "model": connection.model,
                "messages": [
                    {"role": "system", "content": "你是一名严谨的中文技术编辑，擅长在不改变事实的前提下整理文章。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1000,
            },
            timeout=settings.official_ai_timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except httpx.TimeoutException as exc:
        raise AIServiceError("AI 服务响应超时，请稍后重试。") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            message = "AI API Key 无效或无权访问所选模型。"
        elif status == 429:
            message = "AI 服务请求过于频繁或账户额度不足。"
        else:
            message = f"AI 服务请求失败（HTTP {status}）。"
        raise AIServiceError(message) from exc
    except (httpx.RequestError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise AIServiceError("AI 服务返回异常，请检查接口地址和模型配置。") from exc

    if not isinstance(content, str) or not content.strip():
        raise AIServiceError("AI 服务未返回有效文章内容。")
    return content.strip()


def _split_markdown(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for paragraph in text.split("\n\n"):
        if current and current_length + len(paragraph) + 2 > limit:
            chunks.append("\n\n".join(current))
            current = []
            current_length = 0
        if len(paragraph) > limit:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_length = 0
            chunks.extend(
                paragraph[index : index + limit]
                for index in range(0, len(paragraph), limit)
            )
            continue
        current.append(paragraph)
        current_length += len(paragraph) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _validate_connection(connection: AIConnection) -> None:
    parsed = urlparse(connection.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIServiceError("AI Base URL 必须是有效的 HTTP(S) 地址。")
    if not connection.api_key or not connection.model:
        raise AIServiceError("AI API Key 和模型名称不能为空。")
