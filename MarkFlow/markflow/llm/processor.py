from __future__ import annotations
import json
import textwrap
from typing import Generator

from openai import OpenAI
from rich.console import Console

from markflow.config import LLMConfig
from markflow.models import ContentBlock, BlockType, ImageBlock, ParsedDocument

console = Console(highlight=False, force_terminal=True, force_jupyter=False)

LANG_NAMES = {"zh": "中文", "en": "English"}

SYSTEM_ZH = "你是一位技术博客作者，擅长将技术文档改写为清晰易读的博客文章。"
SYSTEM_EN = "You are a technical blogger who rewrites technical documents into clear, engaging blog posts."


class LLMProcessor:
    def __init__(self, cfg: LLMConfig):
        self._cfg = cfg
        self._client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rewrite_content(self, doc: ParsedDocument, console_status: bool = True) -> str:
        """Task 2: heavily compress & reorganise content into blog prose."""
        lang = doc.detected_lang
        draft = _blocks_to_draft(doc.blocks)
        chunks = _split_chunks(draft, self._cfg.chunk_size)

        parts: list[str] = []
        for i, chunk in enumerate(chunks):
            if console_status and len(chunks) > 1:
                console.print(f"  [dim]正文重组 chunk {i+1}/{len(chunks)}...[/dim]")
            parts.append(self._rewrite_chunk(chunk, lang))

        return "\n\n".join(parts)

    def generate_titles(self, doc: ParsedDocument) -> list[str]:
        """Task 1: generate 3 candidate titles."""
        lang = doc.detected_lang
        sample = _blocks_to_draft(doc.blocks)[:1500]
        prompt = _title_prompt(sample, lang)
        resp = self._call(prompt, lang, max_tokens=300)
        return _parse_title_list(resp)

    def generate_description(self, rewritten: str, lang: str) -> str:
        """Task 3: generate 80-150 char description for Hexo Front Matter."""
        prompt = _description_prompt(rewritten[:2000], lang)
        return self._call(prompt, lang, max_tokens=200).strip()

    def generate_tags_categories(
        self, rewritten: str, lang: str
    ) -> tuple[list[str], list[str]]:
        """Task 4: return (tags, categories)."""
        prompt = _tags_prompt(rewritten[:2000], lang)
        resp = self._call(prompt, lang, max_tokens=200)
        return _parse_tags_categories(resp)

    def generate_alt_text(self, img: ImageBlock, context: str, lang: str) -> str:
        """Task 5: generate alt text for one image given surrounding text context."""
        prompt = _alt_prompt(context, lang)
        return self._call(prompt, lang, max_tokens=80).strip()

    def stream_rewrite(self, doc: ParsedDocument) -> Generator[str, None, None]:
        """Streaming version of rewrite_content — yields text chunks."""
        lang = doc.detected_lang
        draft = _blocks_to_draft(doc.blocks)
        chunks = _split_chunks(draft, self._cfg.chunk_size)
        for chunk in chunks:
            yield from self._stream_chunk(chunk, lang)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call(self, user_prompt: str, lang: str, max_tokens: int = 2000) -> str:
        system = SYSTEM_ZH if lang == "zh" else SYSTEM_EN
        resp = self._client.chat.completions.create(
            model=self._cfg.model,
            temperature=self._cfg.temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""

    def _rewrite_chunk(self, chunk: str, lang: str) -> str:
        system = SYSTEM_ZH if lang == "zh" else SYSTEM_EN
        lang_name = LANG_NAMES.get(lang, lang)
        prompt = textwrap.dedent(f"""\
            请将以下文档内容大幅压缩和重组为{lang_name}博客正文段落。
            要求：
            - 保留核心技术细节和关键结论
            - 删除冗余铺垫、重复描述和非必要背景
            - 使用博客叙述风格，段落清晰，逻辑连贯
            - 保留原有的 Markdown 标题层级（# ## ###）
            - 保留代码块（``` ```）和表格原样输出
            - 【强制】原文中所有 [IMG_数字] 标记必须完整保留在改写后的对应位置，不得删除、合并或移动
            - 不要添加额外的开场白或结束语
            - 直接输出改写后的 Markdown 内容

            原文：
            {chunk}
        """) if lang == "zh" else textwrap.dedent(f"""\
            Please heavily compress and reorganise the following content into blog prose in {lang_name}.
            Requirements:
            - Keep core technical details and key conclusions
            - Remove redundant preamble, repetition, and unnecessary background
            - Use a blog narrative style with clear, logical paragraphs
            - Preserve original Markdown heading levels (# ## ###)
            - Keep code blocks (``` ```) and tables as-is
            - [REQUIRED] Every [IMG_N] marker in the source MUST be kept at its corresponding position in the output. Do not delete, merge, or move them.
            - Do not add extra introductions or sign-offs
            - Output only the rewritten Markdown

            Source:
            {chunk}
        """)
        return self._call(prompt, lang, max_tokens=self._cfg.chunk_size * 2)

    def _stream_chunk(self, chunk: str, lang: str) -> Generator[str, None, None]:
        system = SYSTEM_ZH if lang == "zh" else SYSTEM_EN
        lang_name = LANG_NAMES.get(lang, lang)
        prompt = textwrap.dedent(f"""\
            请将以下内容压缩重组为{lang_name}博客正文 Markdown，保留核心技术细节。
            【强制】原文中所有 [IMG_数字] 标记必须完整保留在改写后的对应位置，不得删除。
            直接输出 Markdown。

            原文：
            {chunk}
        """)
        stream = self._client.chat.completions.create(
            model=self._cfg.model,
            temperature=self._cfg.temperature,
            max_tokens=self._cfg.chunk_size * 2,
            stream=True,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        for event in stream:
            delta = event.choices[0].delta.content
            if delta:
                yield delta


# ------------------------------------------------------------------
# Prompt builders
# ------------------------------------------------------------------

def _title_prompt(sample: str, lang: str) -> str:
    if lang == "zh":
        return textwrap.dedent(f"""\
            根据以下文档内容，生成3个适合技术博客的中文标题候选。
            要求：标题简洁吸引人，15字以内，体现文章核心价值。
            以 JSON 数组格式输出，例如：["标题一","标题二","标题三"]

            文档节选：
            {sample}
        """)
    return textwrap.dedent(f"""\
        Generate 3 blog title candidates based on the document below.
        Requirements: concise, engaging, under 10 words, reflect core value.
        Output as JSON array: ["Title One","Title Two","Title Three"]

        Document excerpt:
        {sample}
    """)


def _description_prompt(content: str, lang: str) -> str:
    if lang == "zh":
        return textwrap.dedent(f"""\
            根据以下博客正文，生成一段80-150字的中文摘要，用于 Hexo 博客的 description 字段。
            直接输出摘要文字，不要加引号或额外说明。

            正文：
            {content}
        """)
    return textwrap.dedent(f"""\
        Write an 80-150 word description for the Hexo blog description field based on the content below.
        Output only the description text, no quotes or extra explanation.

        Content:
        {content}
    """)


def _tags_prompt(content: str, lang: str) -> str:
    if lang == "zh":
        return textwrap.dedent(f"""\
            根据以下博客内容，推荐标签和分类，以 JSON 格式输出。
            要求：tags 为3-5个关键词，categories 为1-2个大类。
            格式：{{"tags":["tag1","tag2"],"categories":["分类1"]}}

            内容：
            {content}
        """)
    return textwrap.dedent(f"""\
        Recommend tags and categories for the blog post below, output as JSON.
        Requirements: 3-5 tags as keywords, 1-2 categories.
        Format: {{"tags":["tag1","tag2"],"categories":["Cat1"]}}

        Content:
        {content}
    """)


def _alt_prompt(context: str, lang: str) -> str:
    if lang == "zh":
        return textwrap.dedent(f"""\
            根据以下图片在文章中的上下文，为该图片生成一句简短的中文描述（alt text），15字以内。
            直接输出描述文字，不加引号。

            上下文：
            {context}
        """)
    return textwrap.dedent(f"""\
        Based on the surrounding context below, write a short alt text (under 10 words) for the image.
        Output only the text, no quotes.

        Context:
        {context}
    """)


# ------------------------------------------------------------------
# Parsers
# ------------------------------------------------------------------

def _parse_title_list(resp: str) -> list[str]:
    resp = resp.strip()
    try:
        start = resp.index("[")
        end = resp.rindex("]") + 1
        titles = json.loads(resp[start:end])
        if isinstance(titles, list):
            return [str(t) for t in titles if t]
    except (ValueError, json.JSONDecodeError):
        pass
    # Fallback: split by newline and strip numbering
    import re
    lines = [re.sub(r"^\d+[.)]\s*", "", l).strip().strip('"') for l in resp.splitlines()]
    return [l for l in lines if l][:3]


def _parse_tags_categories(resp: str) -> tuple[list[str], list[str]]:
    resp = resp.strip()
    try:
        start = resp.index("{")
        end = resp.rindex("}") + 1
        data = json.loads(resp[start:end])
        tags = [str(t) for t in data.get("tags", [])]
        cats = [str(c) for c in data.get("categories", [])]
        return tags, cats
    except (ValueError, json.JSONDecodeError):
        return [], []


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _blocks_to_draft(blocks: list[ContentBlock]) -> str:
    parts: list[str] = []
    img_counter = 0
    for b in blocks:
        if b.type == BlockType.IMAGE:
            # Numbered placeholder so LLM can preserve exact position
            parts.append(f"[IMG_{img_counter}]")
            img_counter += 1
        elif b.type == BlockType.HEADING:
            parts.append("#" * b.level + " " + b.content)
        elif b.type == BlockType.CODE:
            parts.append(f"```\n{b.content}\n```")
        elif b.type == BlockType.TABLE:
            parts.append(b.content)
        else:
            parts.append(b.content)
    return "\n\n".join(parts)


def _split_chunks(text: str, chunk_size: int) -> list[str]:
    """Naive split by approximate character count (1 token ≈ 1.5 chars for CJK)."""
    char_limit = chunk_size * 2
    if len(text) <= char_limit:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n\n")
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) > char_limit and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para)

    if current:
        chunks.append("\n\n".join(current))
    return chunks
