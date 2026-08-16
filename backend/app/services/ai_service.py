from __future__ import annotations

import json
import logging
import base64
import re
import time
from dataclasses import dataclass
from datetime import date
from threading import Lock
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)
AI_MERGE_MAX_CHARS = 6000


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
    is_chinese = _is_mostly_chinese(text)
    protected_text = _protect_image_markers(text)
    chunks = _split_markdown(protected_text, 2500)
    plan = ""

    if len(chunks) == 1:
        rewritten = _rewrite_chunk(
            chunks[0],
            filename=filename,
            connection=connection,
            is_chinese=is_chinese,
            plan="",
            index=1,
            total=1,
        )
    else:
        plan = _plan_article(protected_text, filename, connection, is_chinese)
        parts = [
            _rewrite_chunk(
                chunk,
                filename=filename,
                connection=connection,
                is_chinese=is_chinese,
                plan=plan,
                index=index,
                total=len(chunks),
            )
            for index, chunk in enumerate(chunks, start=1)
        ]
        joined_length = len("\n\n".join(parts))
        if joined_length > AI_MERGE_MAX_CHARS:
            logger.info(
                "Using local merge for large rewritten article. filename=%s model=%s chars=%s limit=%s",
                filename,
                connection.model,
                joined_length,
                AI_MERGE_MAX_CHARS,
            )
            rewritten = _merge_parts_locally(parts, filename)
        else:
            try:
                rewritten = _merge_rewritten_parts(parts, filename, connection, is_chinese, plan)
            except AIServiceError as exc:
                logger.warning(
                    "AI merge failed; using locally merged rewritten chunks. filename=%s model=%s error=%s",
                    filename,
                    connection.model,
                    str(exc),
                )
                rewritten = _merge_parts_locally(parts, filename)

    rewritten = _unprotect_image_markers(rewritten.strip())
    original_markers = re.findall(r"\[IMG_(\d+)\]", text)
    rewritten_markers = re.findall(r"\[IMG_(\d+)\]", rewritten)
    if original_markers and rewritten_markers != original_markers:
        logger.warning(
            "AI moved or dropped image markers; rewriting text segments with fixed image anchors. filename=%s",
            filename,
        )
        return _rewrite_text_segments_preserving_image_markers(
            text,
            filename=filename,
            connection=connection,
            is_chinese=is_chinese,
            plan=plan,
        )
    if _rewritten_too_similar(text, rewritten):
        logger.warning(
            "AI rewrite is too similar to source; retrying text segments with fixed image anchors. filename=%s",
            filename,
        )
        return _rewrite_text_segments_preserving_image_markers(
            text,
            filename=filename,
            connection=connection,
            is_chinese=is_chinese,
            plan=plan,
        )
    return rewritten


def _plan_article(text: str, filename: str, connection: AIConnection, is_chinese: bool) -> str:
    excerpt = _compact_for_prompt(text, 6000)
    prompt = (
        "请先为下面的中文草稿制定一份博客文章整理规划。\n"
        "要求：只输出简洁规划，不要写正文；规划必须包含一个文章主标题、章节顺序、每章要保留的重点。\n"
        "不要使用“第一部分/第二部分/第三部分”作为标题。\n\n"
        f"文件名：{filename}\n\n草稿摘录：\n{excerpt}"
        if is_chinese
        else (
            "Create a concise article rewrite plan for the draft below. Output only the plan, not the article. "
            "Include one main title, section order, and key points to preserve. Do not use 'Part 1/Part 2' headings.\n\n"
            f"Filename: {filename}\n\nDraft excerpt:\n{excerpt}"
        )
    )
    return _call_chat(connection, _system_prompt(is_chinese), prompt, max_tokens=900, stage="全文规划").strip()


def _rewrite_chunk(
    text: str,
    *,
    filename: str,
    connection: AIConnection,
    is_chinese: bool,
    plan: str,
    index: int,
    total: int,
) -> str:
    if is_chinese:
        prompt = (
            "请根据全文规划，改写下面这一段草稿为可发布博客正文片段。\n"
            "硬性要求：\n"
            "- 必须使用中文输出，不要翻译成英文。\n"
            "- 只写当前片段内容，不要写“第一部分/第二部分/第几部分/以下是/整理结果/注”等读者不需要看到的说明。\n"
            "- 除非这是全文第一段且原文已有总标题，否则不要生成一级标题 #；章节标题从 ## 或 ### 开始。\n"
            "- 保留事实、数字、链接、代码块、表格。\n"
            "- 每个 draft-to-blog://IMG_ 图片占位符必须原样保留一次，放在原上下文附近，不要移动到文末。\n"
            "- 不要虚构信息，不要输出代码围栏包裹全文。\n\n"
            f"文件名：{filename}\n全文规划：\n{plan or '单段文章，无需额外规划。'}\n\n"
            f"当前片段：{index}/{total}\n{text}"
        )
    else:
        prompt = (
            "Rewrite this draft chunk as a publishable article segment following the overall plan.\n"
            "Hard requirements:\n"
            "- Preserve the source language.\n"
            "- Write only this segment. Do not mention Part 1/Part 2, notes, rewrite result, or editorial comments.\n"
            "- Do not create an H1 heading unless this is the first segment and the source has an overall title; use H2/H3 for sections.\n"
            "- Preserve facts, numbers, links, code blocks, tables.\n"
            "- Keep every draft-to-blog://IMG_ image placeholder exactly once near its original context; never move images to the end.\n"
            "- Keep every @@DTBIMAGE...@@ token exactly as written; do not rewrite, translate, summarize, or remove it.\n"
            "- Preserve image captions such as Figure/Image labels adjacent to their image; do not collapse multiple images together.\n"
            "- Do not invent information or wrap the whole output in a code fence.\n\n"
            f"Filename: {filename}\nOverall plan:\n{plan or 'Single-segment article.'}\n\n"
            f"Current segment: {index}/{total}\n{text}"
        )
    return _call_chat(
        connection,
        _system_prompt(is_chinese),
        prompt,
        max_tokens=1800,
        stage=f"分块改写 {index}/{total}",
    ).strip()


def _merge_rewritten_parts(
    parts: list[str],
    filename: str,
    connection: AIConnection,
    is_chinese: bool,
    plan: str,
) -> str:
    joined = "\n\n".join(parts)
    prompt = (
        "请将下面多个已改写片段统一合并成一篇完整中文 Markdown 博客。\n"
        "硬性要求：\n"
        "- 只保留一个一级标题 #。\n"
        "- 删除“第一部分/第二部分/第几部分/以下是整理结果/注：此部分”等编辑痕迹。\n"
        "- 保留所有图片占位符 draft-to-blog://IMG_N，且每个占位符最多出现一次；不要移动到文末。\n"
        "- 合并重复标题，修正标题层级，保持正文自然连贯。\n"
        "- 只输出 Markdown 正文。\n\n"
        f"文件名：{filename}\n全文规划：\n{plan}\n\n片段：\n{joined}"
        if is_chinese
        else (
            "Merge the rewritten chunks into one complete Markdown blog article.\n"
            "Hard requirements: keep only one H1, remove Part 1/Part 2/editorial notes, preserve every "
            "draft-to-blog://IMG_N placeholder at most once near its context, preserve image captions, "
            "keep every @@DTBIMAGE...@@ token exactly as written, "
            "do not collapse multiple images together, merge duplicate headings, output only Markdown.\n\n"
            f"Filename: {filename}\nPlan:\n{plan}\n\nChunks:\n{joined}"
        )
    )
    return _call_chat(connection, _system_prompt(is_chinese), prompt, max_tokens=4000, stage="统一合并").strip()


def _call_chat(
    connection: AIConnection,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    stage: str,
) -> str:
    last_error: AIServiceError | None = None
    for attempt in range(1, 3):
        if connection.uses_official_quota:
            _quota.consume(settings.official_ai_daily_request_limit)
        try:
            with httpx.Client(timeout=settings.official_ai_timeout_seconds, trust_env=settings.official_ai_trust_env) as client:
                response = client.post(
                    f"{connection.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {connection.api_key}"},
                    json={
                        "model": connection.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": max_tokens,
                    },
                )
            response.raise_for_status()
            content = _extract_chat_content(response, stage)
            break
        except httpx.TimeoutException as exc:
            last_error = AIServiceError(f"AI 服务在「{stage}」阶段响应超时：{type(exc).__name__}: {exc}")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                message = "AI API Key 无效或无权访问所选模型。"
            elif status == 429:
                message = "AI 服务请求过于频繁或账户额度不足。"
            else:
                body = exc.response.text[:300].replace("\n", " ")
                message = f"AI 服务在「{stage}」阶段请求失败（HTTP {status}）：{body}"
            raise AIServiceError(message) from exc
        except httpx.RequestError as exc:
            last_error = AIServiceError(f"AI 服务在「{stage}」阶段网络请求异常：{type(exc).__name__}: {exc}")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIServiceError(f"AI 服务在「{stage}」阶段响应解析异常：{type(exc).__name__}: {exc}") from exc
        if attempt < 2:
            logger.warning("AI call failed; retrying. stage=%s attempt=%s error=%s", stage, attempt, last_error)
            time.sleep(2)
    else:
        raise last_error or AIServiceError(f"AI 服务在「{stage}」阶段请求失败。")
    if not isinstance(content, str) or not content.strip():
        raise AIServiceError(f"AI 服务在「{stage}」阶段未返回有效文章内容。")
    return content


def _extract_chat_content(response: httpx.Response, stage: str) -> str:
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        preview = response.text[:300].replace("\n", " ")
        raise AIServiceError(f"AI 服务在「{stage}」阶段返回了非 JSON 响应：{preview}") from exc
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        preview = json.dumps(data, ensure_ascii=False)[:300]
        raise AIServiceError(f"AI 服务在「{stage}」阶段返回格式异常：{preview}") from exc


def _system_prompt(is_chinese: bool) -> str:
    if is_chinese:
        return (
            "你是一名严谨的中文技术编辑。必须保持原文语言；如果原文是中文，输出必须是中文。"
            "你只做结构整理和表达优化，不虚构信息，不输出编辑说明，并严格保留图片占位符位置。"
        )
    return (
        "You are a careful technical editor. Preserve the source language and facts, "
        "do not output editorial notes, and preserve image placeholders near their original positions."
    )


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
            chunks.extend(paragraph[index : index + limit] for index in range(0, len(paragraph), limit))
            continue
        current.append(paragraph)
        current_length += len(paragraph) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _compact_for_prompt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n\n...（中间内容省略，仅用于规划）...\n\n{tail}"


def _build_rewrite_prompt(text: str, filename: str, is_chinese: bool) -> str:
    # Kept for tests and compatibility with older imports.
    return _rewrite_chunk_prompt_for_tests(text, filename, is_chinese)


def _rewrite_chunk_prompt_for_tests(text: str, filename: str, is_chinese: bool) -> str:
    if is_chinese:
        return (
            "请将下面的草稿整理成可直接发布的中文 Markdown 文章。\n"
            "要求：必须使用中文输出，不要翻译成英文；不要输出“注：”“以下是整理结果”“此部分原文”等编辑说明。\n"
            f"\n文件名：{filename}\n\n草稿：\n{text}"
        )
    return (
        "Please reorganize the draft below into a publishable Markdown article. Preserve source language and do not "
        f"output editorial notes.\nFilename: {filename}\n\nDraft:\n{text}"
    )


def _is_mostly_chinese(text: str) -> bool:
    sample = text[:4000]
    cjk = sum(1 for char in sample if "\u4e00" <= char <= "\u9fff")
    letters = sum(1 for char in sample if char.isalpha())
    return cjk >= 8 and cjk / max(letters, 1) >= 0.15


def _protect_image_markers(text: str) -> str:
    parts = text.split("\n\n")
    protected: list[str] = []
    for part in parts:
        marker = re.fullmatch(r"\s*\[IMG_(\d+)]\s*", part)
        if not marker:
            protected.append(part)
            continue
        marker_id = marker.group(1)
        caption = protected[-1].strip() if protected else ""
        if _looks_like_image_caption(caption):
            protected.pop()
            encoded_caption = _encode_image_caption(caption)
        else:
            encoded_caption = ""
        protected.append(f"@@DTBIMAGE{marker_id}:{encoded_caption}@@")
    return "\n\n".join(protected)


def _unprotect_image_markers(text: str) -> str:
    def replace_token(match: re.Match[str]) -> str:
        marker = f"[IMG_{match.group(1)}]"
        caption = _decode_image_caption(match.group(2) or "")
        if caption:
            return f"{caption}\n\n{marker}"
        return marker

    def replace(match: re.Match[str]) -> str:
        alt = re.sub(r"\s+", " ", match.group(1).strip())
        marker = f"[IMG_{match.group(2)}]"
        if alt and not re.fullmatch(r"IMG_?\d+|image[-_\s]?\d+", alt, flags=re.I):
            return f"{alt}\n\n{marker}"
        return marker

    text = re.sub(r"@@DTBIMAGE(\d+):([A-Za-z0-9_-]*)@@", replace_token, text)
    text = re.sub(r"!\[([^\]]*)]\(draft-to-blog://IMG_(\d+)\)", replace, text)
    return re.sub(r"draft-to-blog://IMG_(\d+)", r"[IMG_\1]", text)


def _encode_image_caption(caption: str) -> str:
    normalized = re.sub(r"\s+", " ", caption.strip())
    return base64.urlsafe_b64encode(normalized.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_image_caption(encoded: str) -> str:
    if not encoded:
        return ""
    try:
        padding = "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def _looks_like_image_caption(value: str) -> bool:
    caption = re.sub(r"\s+", " ", value.strip())
    if not caption or len(caption) > 80 or "\n" in value.strip():
        return False
    return bool(re.search(r"(?:示例图|图片|图\s*\d|图表|Figure|Fig\.|Image)", caption, flags=re.I))


def _merge_parts_locally(parts: list[str], filename: str) -> str:
    title = _safe_markdown_title(filename)
    seen_h1 = False
    seen_images: set[str] = set()
    lines: list[str] = []
    for raw_line in "\n\n".join(parts).splitlines():
        line = raw_line.rstrip()
        if line.startswith("# "):
            if seen_h1:
                line = "#" + line
            else:
                seen_h1 = True
        image_marker = re.search(r"draft-to-blog://IMG_(\d+)|\[IMG_(\d+)\]", line)
        if image_marker:
            marker_id = image_marker.group(1) or image_marker.group(2)
            if marker_id in seen_images:
                continue
            seen_images.add(marker_id)
        lines.append(line)
    merged = "\n".join(lines).strip()
    if not seen_h1:
        merged = f"# {title}\n\n{merged}"
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    return merged


def _safe_markdown_title(filename: str) -> str:
    title = re.sub(r"\.[^.]+$", "", filename).strip().replace("-", " ")
    return title or "整理后的文章"


def _restore_missing_image_markers(original: str, rewritten: str) -> str:
    original_markers = re.findall(r"\[IMG_(\d+)\]", original)
    if not original_markers:
        return rewritten

    present = set(re.findall(r"\[IMG_(\d+)\]", rewritten))
    result = rewritten
    for marker_id in original_markers:
        if marker_id in present:
            continue
        marker = f"[IMG_{marker_id}]"
        caption = _caption_for_marker(original, marker)
        replacement = f"{caption}\n\n{marker}" if caption and caption not in result else marker
        before, after = _marker_context(original, marker)
        inserted = False
        if before:
            position = _find_context_end(result, before)
            if position >= 0:
                result = result[:position].rstrip() + f"\n\n{replacement}\n\n" + result[position:].lstrip()
                inserted = True
        if not inserted and after:
            position = _find_context_start(result, after)
            if position >= 0:
                result = result[:position].rstrip() + f"\n\n{replacement}\n\n" + result[position:].lstrip()
                inserted = True
        if not inserted:
            result = result.rstrip() + f"\n\n{replacement}"
        present.add(marker_id)
    return result


def _reconcile_image_marker_positions(original: str, rewritten: str) -> str:
    original_markers = re.findall(r"\[IMG_(\d+)\]", original)
    if not original_markers:
        return rewritten

    present_markers = re.findall(r"\[IMG_(\d+)\]", rewritten)
    if present_markers == original_markers:
        return rewritten

    cleaned = re.sub(r"(?m)^\s*\[IMG_\d+]\s*$\n?", "", rewritten)
    cleaned = re.sub(r"\s*\[IMG_\d+]\s*", "\n\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    result = cleaned
    cursor = 0
    for group_markers, before, after in _image_marker_groups(original):
        replacement = "\n\n".join(group_markers)
        inserted = False
        if before:
            position = _find_context_end_after(result, before, cursor)
            if position >= 0:
                result = result[:position].rstrip() + f"\n\n{replacement}\n\n" + result[position:].lstrip()
                cursor = position + len(replacement) + 4
                inserted = True
        if not inserted and after:
            position = _find_context_start_after(result, after, cursor)
            if position >= 0:
                result = result[:position].rstrip() + f"\n\n{replacement}\n\n" + result[position:].lstrip()
                cursor = position + len(replacement) + 4
                inserted = True
        if not inserted:
            result = result.rstrip() + f"\n\n{replacement}"
            cursor = len(result)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def _image_marker_groups(text: str) -> list[tuple[list[str], str, str]]:
    parts = [part.strip() for part in text.split("\n\n") if part.strip()]
    groups: list[tuple[list[str], str, str]] = []
    index = 0
    while index < len(parts):
        marker = re.fullmatch(r"\[IMG_(\d+)]", parts[index])
        if not marker:
            index += 1
            continue
        markers: list[str] = []
        start = index
        while index < len(parts) and re.fullmatch(r"\[IMG_(\d+)]", parts[index]):
            markers.append(parts[index])
            index += 1
        before = _nearest_context(parts[:start], reverse=True)
        after = _nearest_context(parts[index:], reverse=False)
        groups.append((markers, before, after))
    return groups


def _rewrite_text_segments_preserving_image_markers(
    text: str,
    *,
    filename: str,
    connection: AIConnection,
    is_chinese: bool,
    plan: str,
) -> str:
    units = _split_text_and_image_units(text)
    text_units = [
        value
        for kind, value in units
        if kind == "text" and _should_rewrite_text_segment(value)
    ]
    total = max(len(text_units), 1)
    rewritten_units: list[str] = []
    text_index = 0

    for kind, value in units:
        if kind == "image":
            rewritten_units.append(value)
            continue
        if not _should_rewrite_text_segment(value):
            rewritten_units.append(value)
            continue

        text_index += 1
        try:
            rewritten = _rewrite_chunk(
                value,
                filename=filename,
                connection=connection,
                is_chinese=is_chinese,
                plan=plan,
                index=text_index,
                total=total,
            )
        except AIServiceError as exc:
            logger.warning(
                "AI segment rewrite failed; keeping original segment. filename=%s segment=%s/%s error=%s",
                filename,
                text_index,
                total,
                str(exc),
            )
            rewritten_units.append(value)
            continue

        cleaned = _remove_image_markers_from_segment(_unprotect_image_markers(rewritten).strip())
        rewritten_units.append(cleaned or value)

    result = "\n\n".join(unit.strip() for unit in rewritten_units if unit.strip())
    return _merge_parts_locally([result], filename)


def _split_text_and_image_units(text: str) -> list[tuple[str, str]]:
    parts = [part.strip() for part in text.split("\n\n") if part.strip()]
    units: list[tuple[str, str]] = []
    buffer: list[str] = []
    index = 0

    def flush_text() -> None:
        if buffer:
            units.append(("text", "\n\n".join(buffer)))
            buffer.clear()

    while index < len(parts):
        if re.fullmatch(r"\[IMG_\d+]", parts[index]):
            flush_text()
            images: list[str] = []
            while index < len(parts) and re.fullmatch(r"\[IMG_\d+]", parts[index]):
                images.append(parts[index])
                index += 1
            units.append(("image", "\n\n".join(images)))
            continue
        buffer.append(parts[index])
        index += 1

    flush_text()
    return units


def _should_rewrite_text_segment(text: str) -> bool:
    cleaned = re.sub(r"\s+", "", text)
    return len(cleaned) >= 30


def _remove_image_markers_from_segment(text: str) -> str:
    text = re.sub(r"(?m)^\s*\[IMG_\d+]\s*$\n?", "", text)
    text = re.sub(r"\s*\[IMG_\d+]\s*", "\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _rewritten_too_similar(original: str, rewritten: str) -> bool:
    original_norm = _normalize_for_similarity(original)
    rewritten_norm = _normalize_for_similarity(rewritten)
    if len(original_norm) < 120 or len(rewritten_norm) < 120:
        return original_norm == rewritten_norm
    if original_norm == rewritten_norm:
        return True
    common_prefix = 0
    for left, right in zip(original_norm, rewritten_norm):
        if left != right:
            break
        common_prefix += 1
    return common_prefix / max(len(original_norm), 1) > 0.97 and abs(len(original_norm) - len(rewritten_norm)) < 20


def _normalize_for_similarity(text: str) -> str:
    text = _unprotect_image_markers(text)
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
    text = re.sub(r"\[IMG_\d+]", "", text)
    text = re.sub(r"#+\s*", "", text)
    return re.sub(r"\s+", "", text).strip()


def _caption_for_marker(text: str, marker: str) -> str:
    before_text, _, _ = text.partition(marker)
    parts = [part.strip() for part in before_text.split("\n\n") if part.strip()]
    if not parts:
        return ""
    caption = parts[-1]
    return caption if _looks_like_image_caption(caption) else ""


def _marker_context(text: str, marker: str) -> tuple[str, str]:
    before_text, _, after_text = text.partition(marker)
    before = _nearest_context(before_text.split("\n\n"), reverse=True)
    after = _nearest_context(after_text.split("\n\n"), reverse=False)
    return before, after


def _nearest_context(parts: list[str], reverse: bool) -> str:
    iterable = reversed(parts) if reverse else iter(parts)
    for part in iterable:
        cleaned = re.sub(r"\[IMG_\d+\]", "", part).strip()
        if len(cleaned) >= 4:
            return cleaned[-80:] if reverse else cleaned[:80]
    return ""


def _find_context_end(text: str, context: str) -> int:
    snippet = context.strip()
    for size in (80, 50, 30, 16):
        needle = snippet[-size:] if len(snippet) > size else snippet
        index = text.find(needle)
        if index >= 0:
            return index + len(needle)
    return -1


def _find_context_start(text: str, context: str) -> int:
    snippet = context.strip()
    for size in (80, 50, 30, 16):
        needle = snippet[:size] if len(snippet) > size else snippet
        index = text.find(needle)
        if index >= 0:
            return index
    return -1


def _find_context_end_after(text: str, context: str, start: int) -> int:
    snippet = context.strip()
    for size in (80, 50, 30, 16):
        needle = snippet[-size:] if len(snippet) > size else snippet
        index = text.find(needle, start)
        if index >= 0:
            return index + len(needle)
    return -1


def _find_context_start_after(text: str, context: str, start: int) -> int:
    snippet = context.strip()
    for size in (80, 50, 30, 16):
        needle = snippet[:size] if len(snippet) > size else snippet
        index = text.find(needle, start)
        if index >= 0:
            return index
    return -1


def _plan_article(text: str, filename: str, connection: AIConnection, is_chinese: bool) -> str:
    excerpt = _compact_for_prompt(text, 6000)
    if is_chinese:
        prompt = (
            "请先为下面的中文草稿制定一份博客文章整理规划。\n"
            "要求：只输出简洁规划，不要写正文；规划必须包含一个文章主标题、章节顺序、每章要保留的重点。\n"
            "不要使用“第一部分/第二部分/第三部分”作为标题。\n"
            "图片占位符（如 @@DTBIMAGE12:...@@）代表原文图片，规划时不得建议合并、删除或移动图片。\n\n"
            f"文件名：{filename}\n\n草稿摘录：\n{excerpt}"
        )
    else:
        prompt = (
            "Create a concise article rewrite plan for the draft below. Output only the plan, not the article. "
            "Include one main title, section order, and key points to preserve. Do not use 'Part 1/Part 2' headings. "
            "Image placeholders such as @@DTBIMAGE12:...@@ are fixed anchors; do not merge, remove, or move them.\n\n"
            f"Filename: {filename}\n\nDraft excerpt:\n{excerpt}"
        )
    return _call_chat(connection, _system_prompt(is_chinese), prompt, max_tokens=900, stage="全文规划").strip()


def _rewrite_chunk(
    text: str,
    *,
    filename: str,
    connection: AIConnection,
    is_chinese: bool,
    plan: str,
    index: int,
    total: int,
) -> str:
    if is_chinese:
        prompt = (
            "请根据全文规划，改写下面这一段草稿为可发布博客正文片段。\n"
            "硬性要求：\n"
            "- 必须使用中文输出，不要翻译成英文。\n"
            "- 只写当前片段内容，不要写“第一部分/第二部分/第几部分/以下是整理结果/注”等读者不需要看到的说明。\n"
            "- 除非这是全文第一段且原文已有总标题，否则不要生成一级标题 #；章节标题从 ## 或 ### 开始。\n"
            "- 保留事实、数字、链接、代码块、表格。\n"
            "- 每个 @@DTBIMAGE...@@ 图片占位符必须原样保留一次，不能改写、翻译、删减或变成 Markdown 图片。\n"
            "- 图片占位符必须紧贴原来的上下文；不要提前、延后、集中到段落末尾或移动到文末。\n"
            "- 连续图片占位符要保持原顺序，不要合并成一张图，也不要插入到不相关段落。\n"
            "- 保留图片图注（如“示例图”“图 1”“图片说明”）并让图注紧邻对应图片。\n"
            "- 必须做可见的表达优化：不要逐句照抄原文；在不改变事实的前提下，重组句子、调整衔接、压缩重复表达，并保持自然口语感。\n"
            "- 如果原文已经比较顺，也要改写成另一种自然说法，不能只替换图片或空白。\n"
            "- 不要虚构信息，不要输出代码围栏包裹全文。\n\n"
            f"文件名：{filename}\n全文规划：\n{plan or '单段文章，无需额外规划。'}\n\n"
            f"当前片段：{index}/{total}\n{text}"
        )
    else:
        prompt = (
            "Rewrite this draft chunk as a publishable article segment following the overall plan.\n"
            "Hard requirements:\n"
            "- Preserve the source language.\n"
            "- Write only this segment. Do not mention Part 1/Part 2, notes, rewrite result, or editorial comments.\n"
            "- Do not create an H1 heading unless this is the first segment and the source has an overall title; use H2/H3 for sections.\n"
            "- Preserve facts, numbers, links, code blocks, tables.\n"
            "- Keep every @@DTBIMAGE...@@ image placeholder exactly once as written; do not rewrite, translate, summarize, or remove it.\n"
            "- Keep image placeholders near their original context; never move images earlier, later, or to the end.\n"
            "- Preserve consecutive image placeholders in their original order; do not collapse multiple images together.\n"
            "- Preserve image captions such as Figure/Image labels adjacent to their image.\n"
            "- Make visible editorial improvements. Do not copy sentences verbatim; reorganize wording, transitions, and repeated phrasing while preserving facts and a natural conversational tone.\n"
            "- If the source is already readable, still rewrite it into a different natural phrasing; changing only images or whitespace is not enough.\n"
            "- Do not invent information or wrap the whole output in a code fence.\n\n"
            f"Filename: {filename}\nOverall plan:\n{plan or 'Single-segment article.'}\n\n"
            f"Current segment: {index}/{total}\n{text}"
        )
    return _call_chat(
        connection,
        _system_prompt(is_chinese),
        prompt,
        max_tokens=1800,
        stage=f"分块改写 {index}/{total}",
    ).strip()


def _merge_rewritten_parts(
    parts: list[str],
    filename: str,
    connection: AIConnection,
    is_chinese: bool,
    plan: str,
) -> str:
    joined = "\n\n".join(parts)
    if is_chinese:
        prompt = (
            "请将下面多个已改写片段统一合并成一篇完整中文 Markdown 博客。\n"
            "硬性要求：\n"
            "- 只保留一个一级标题 #。\n"
            "- 删除“第一部分/第二部分/第几部分/以下是整理结果/注：此部分”等编辑痕迹。\n"
            "- 保留所有 @@DTBIMAGE...@@ 图片占位符，且每个占位符最多出现一次。\n"
            "- 不要移动图片占位符；必须保持它们与原片段中相邻文本的关系和相对顺序。\n"
            "- 连续图片占位符必须保持连续和原顺序，不要插入到其它章节或不相关段落。\n"
            "- 合并重复标题，修正标题层级，保持正文自然连贯。\n"
            "- 只输出 Markdown 正文。\n\n"
            f"文件名：{filename}\n全文规划：\n{plan}\n\n片段：\n{joined}"
        )
    else:
        prompt = (
            "Merge the rewritten chunks into one complete Markdown blog article.\n"
            "Hard requirements: keep only one H1, remove Part 1/Part 2/editorial notes, preserve every "
            "@@DTBIMAGE...@@ placeholder at most once near its context, preserve image captions, "
            "do not collapse multiple images together, merge duplicate headings, output only Markdown.\n\n"
            f"Filename: {filename}\nPlan:\n{plan}\n\nChunks:\n{joined}"
        )
    return _call_chat(connection, _system_prompt(is_chinese), prompt, max_tokens=4000, stage="统一合并").strip()


def _system_prompt(is_chinese: bool) -> str:
    if is_chinese:
        return (
            "你是一名严谨的中文技术编辑。必须保持原文语言；如果原文是中文，输出必须是中文。"
            "你只做结构整理和表达优化，不虚构信息，不输出编辑说明。"
            "图片占位符是内容锚点，必须原样保留并保持在原上下文附近。"
        )
    return (
        "You are a careful technical editor. Preserve the source language and facts, "
        "do not output editorial notes, and keep image placeholders near their original positions."
    )


def _compact_for_prompt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n\n...（中间内容省略，仅用于规划）...\n\n{tail}"


def _rewrite_chunk_prompt_for_tests(text: str, filename: str, is_chinese: bool) -> str:
    if is_chinese:
        return (
            "请将下面的草稿整理成可直接发布的中文 Markdown 文章。\n"
            "要求：必须使用中文输出，不要翻译成英文；不要输出“注：”“以下是整理结果”“此部分原文”等编辑说明。\n"
            "保留所有 @@DTBIMAGE...@@ 图片占位符，且保持在原上下文附近，不要移动到文末。\n"
            f"\n文件名：{filename}\n\n草稿：\n{text}"
        )
    return (
        "Please reorganize the draft below into a publishable Markdown article. Preserve source language and do not "
        "output editorial notes. Keep every @@DTBIMAGE...@@ image placeholder near its original context.\n"
        f"Filename: {filename}\n\nDraft:\n{text}"
    )


def _looks_like_image_caption(value: str) -> bool:
    caption = re.sub(r"\s+", " ", value.strip())
    if not caption or len(caption) > 80 or "\n" in value.strip():
        return False
    return bool(re.search(r"(?:示例图|图片|图\s*\d|图表|Figure|Fig\.|Image)", caption, flags=re.I))


def _validate_connection(connection: AIConnection) -> None:
    parsed = urlparse(connection.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AIServiceError("AI Base URL 必须是有效的 HTTP(S) 地址。")
    if not connection.api_key or not connection.model:
        raise AIServiceError("AI API Key 和模型名称不能为空。")
