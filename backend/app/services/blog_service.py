from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Literal

import fitz
import yaml
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


class BlockType(str):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    IMAGE = "image"
    TABLE = "table"
    CODE = "code"
    LIST = "list"


@dataclass
class ImageBlock:
    index: int
    data: bytes
    ext: str
    md5: str
    paragraph_idx: int
    alt_text: str = ""


@dataclass
class ContentBlock:
    type: str
    content: str = ""
    level: int = 0
    language: str = ""
    image: ImageBlock | None = None


@dataclass
class ParsedDocument:
    blocks: list[ContentBlock] = field(default_factory=list)
    images: list[ImageBlock] = field(default_factory=list)
    detected_lang: str = "zh"
    title_hint: str = ""


def parse_docx(content: bytes) -> ParsedDocument:
    try:
        document = Document(BytesIO(content))
    except Exception as exc:
        raise ValueError("DOCX 文件无法读取，可能已经损坏或加密。") from exc

    blocks: list[ContentBlock] = []
    images: list[ImageBlock] = []
    seen_md5: dict[str, int] = {}
    para_idx = 0

    for element in document.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
        if tag == "p":
            paragraph = Paragraph(element, document)
            block, image = _parse_docx_paragraph(paragraph, para_idx, seen_md5, document)
            if image:
                images.append(image)
            if block:
                blocks.append(block)
            para_idx += 1
        elif tag == "tbl":
            table_block = _parse_docx_table(Table(element, document))
            if table_block:
                blocks.append(table_block)

    return ParsedDocument(
        blocks=blocks,
        images=images,
        detected_lang=_detect_language(" ".join(p.text for p in document.paragraphs[:20])),
        title_hint=_extract_docx_title(document),
    )


def parse_pdf(content: bytes) -> ParsedDocument:
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ValueError("PDF 文件无法读取，可能已经损坏或加密。") from exc
    if document.needs_pass:
        raise ValueError("暂不支持加密 PDF，请先解除密码。")

    blocks: list[ContentBlock] = []
    images: list[ImageBlock] = []
    seen_md5: dict[str, int] = {}

    try:
        for page in document:
            page_dict = page.get_text("dict")
            for raw_block in page_dict.get("blocks", []):
                if raw_block.get("type") == 0:
                    text, size, is_bold, is_mono = _extract_pdf_text_block(raw_block)
                    if text:
                        blocks.append(_classify_pdf_text(text, size, is_bold, is_mono))
                elif raw_block.get("type") == 1:
                    data = raw_block.get("image", b"")
                    if len(data) < 1024:
                        continue
                    md5 = hashlib.md5(data).hexdigest()
                    if md5 in seen_md5:
                        continue
                    ext = raw_block.get("ext", "png")
                    if ext == "jpeg":
                        ext = "jpg"
                    index = len(seen_md5)
                    seen_md5[md5] = index
                    image = ImageBlock(index=index, data=data, ext=ext, md5=md5, paragraph_idx=len(blocks))
                    images.append(image)
                    blocks.append(ContentBlock(type=BlockType.IMAGE, image=image))
    finally:
        document.close()

    text_sample = " ".join(block.content for block in blocks[:30] if block.content)
    return ParsedDocument(
        blocks=blocks,
        images=images,
        detected_lang=_detect_language(text_sample),
        title_hint=_guess_title(blocks),
    )


def blocks_to_markdown(parsed: ParsedDocument) -> str:
    parts: list[str] = []
    for block in parsed.blocks:
        if block.type == BlockType.IMAGE and block.image:
            parts.append(f"[IMG_{block.image.index}]")
        elif block.type == BlockType.HEADING:
            parts.append(f"{'#' * max(block.level, 1)} {block.content}")
        elif block.type == BlockType.CODE:
            language = block.language or ""
            parts.append(f"```{language}\n{block.content}\n```")
        elif block.content:
            parts.append(block.content)
    return "\n\n".join(part for part in parts if part)


def inject_asset_images(content: str, assets: list[dict]) -> str:
    if not assets:
        return content

    used: set[int] = set()

    def image_markdown(index: int) -> str:
        if index >= len(assets):
            return ""
        asset = assets[index]
        url = asset.get("url") or asset.get("local_path") or asset.get("filename") or ""
        alt = Path(str(asset.get("filename") or f"image-{index + 1}")).stem
        return f"![{alt}]({url})"

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        used.add(index)
        return image_markdown(index)

    rendered = re.sub(r"\[IMG_(\d+)\]", replace, content)
    missed = [index for index, _ in enumerate(assets) if index not in used]
    if missed:
        rendered = rendered.rstrip() + "\n\n" + "\n\n".join(image_markdown(index) for index in missed)
    return rendered


def render_blog_markdown(
    body: str,
    filename: str,
    assets: list[dict],
    preset: Literal["hexo", "hugo"] = "hexo",
) -> str:
    title = _first_markdown_title(body) or Path(filename).stem
    description = _description_from_body(body)
    categories, tags = _infer_taxonomy(body, filename)
    cover = next((asset.get("url") for asset in assets if asset.get("url")), "")
    now = datetime.now(timezone(timedelta(hours=8)))

    if preset == "hugo":
        date_value = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        front_matter: dict = {
            "title": title,
            "date": date_value,
            "lastmod": date_value,
            "tags": tags,
            "categories": categories,
            "description": description,
        }
        if cover:
            front_matter["cover"] = {"image": cover}
    else:
        date_value = now.strftime("%Y-%m-%d %H:%M:%S")
        front_matter = {
            "title": title,
            "date": date_value,
            "updated": date_value,
            "tags": tags,
            "categories": categories,
            "description": description,
        }
        if cover:
            front_matter["cover"] = cover

    yaml_text = yaml.dump(front_matter, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()
    return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"


def _parse_docx_paragraph(
    paragraph: Paragraph,
    para_idx: int,
    seen_md5: dict[str, int],
    document: Document,
) -> tuple[ContentBlock | None, ImageBlock | None]:
    image = _extract_docx_image(paragraph, para_idx, seen_md5, document)
    if image:
        return ContentBlock(type=BlockType.IMAGE, image=image), image

    text = paragraph.text.strip()
    if not text:
        return None, None
    style_name = (paragraph.style.name if paragraph.style else "").lower()
    if style_name.startswith("heading"):
        match = re.search(r"(\d+)", style_name)
        level = min(max(int(match.group(1)) if match else 1, 1), 4)
        return ContentBlock(type=BlockType.HEADING, content=text, level=level), None
    if "code" in style_name or style_name in {"macro text", "html preformatted"}:
        return ContentBlock(type=BlockType.CODE, content=text), None
    if "list" in style_name:
        prefix = "1. " if paragraph._p.find(qn("w:numPr")) is not None else "- "
        return ContentBlock(type=BlockType.LIST, content=prefix + text), None
    return ContentBlock(type=BlockType.PARAGRAPH, content=text), None


def _extract_docx_image(
    paragraph: Paragraph,
    para_idx: int,
    seen_md5: dict[str, int],
    document: Document,
) -> ImageBlock | None:
    drawing = paragraph._p.find(".//" + qn("a:blip"))
    if drawing is None:
        return None
    embed = drawing.get(qn("r:embed"))
    if not embed:
        return None
    try:
        image_part = document.part.related_parts[embed]
    except KeyError:
        return None
    data = image_part.blob
    md5 = hashlib.md5(data).hexdigest()
    if md5 in seen_md5:
        return None
    index = len(seen_md5)
    seen_md5[md5] = index
    return ImageBlock(index=index, data=data, ext=_content_type_to_ext(image_part.content_type), md5=md5, paragraph_idx=para_idx)


def _parse_docx_table(table: Table) -> ContentBlock | None:
    if not table.rows:
        return None
    lines: list[str] = []
    for index, row in enumerate(table.rows):
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        lines.append("| " + " | ".join(cells) + " |")
        if index == 0:
            lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return ContentBlock(type=BlockType.TABLE, content="\n".join(lines))


def _extract_pdf_text_block(raw_block: dict) -> tuple[str, float, bool, bool]:
    lines: list[str] = []
    sizes: list[float] = []
    fonts: list[str] = []
    for line in raw_block.get("lines", []):
        spans = line.get("spans", [])
        text = "".join(span.get("text", "") for span in spans).strip()
        if text:
            lines.append(text)
        sizes.extend(float(span.get("size", 12)) for span in spans if span.get("size"))
        fonts.extend(str(span.get("font", "")).lower() for span in spans)
    font_text = " ".join(fonts)
    return (
        "\n".join(lines).strip(),
        sum(sizes) / len(sizes) if sizes else 12,
        any(token in font_text for token in ("bold", "black", "heavy")),
        any(token in font_text for token in ("mono", "courier", "consol", "code")),
    )


def _classify_pdf_text(text: str, size: float, is_bold: bool, is_mono: bool) -> ContentBlock:
    if is_mono:
        return ContentBlock(type=BlockType.CODE, content=text)
    if size >= 18 or (size >= 15 and is_bold):
        return ContentBlock(type=BlockType.HEADING, content=text, level=1)
    if size >= 14 or (size >= 12 and is_bold):
        return ContentBlock(type=BlockType.HEADING, content=text, level=2)
    if re.match(r"^[•·▪◦\-\*]\s+", text) or re.match(r"^\d+[.)]\s+", text):
        return ContentBlock(type=BlockType.LIST, content="- " + re.sub(r"^[•·▪◦\-\*\d.)]+\s+", "", text))
    return ContentBlock(type=BlockType.PARAGRAPH, content=text)


def _extract_docx_title(document: Document) -> str:
    for paragraph in document.paragraphs:
        style = (paragraph.style.name if paragraph.style else "").lower()
        text = paragraph.text.strip()
        if text and (style == "title" or style.startswith("heading 1")):
            return text
    return ""


def _guess_title(blocks: list[ContentBlock]) -> str:
    for block in blocks[:8]:
        if block.type == BlockType.HEADING and block.content:
            return block.content
    return ""


def _first_markdown_title(body: str) -> str:
    match = re.search(r"^#\s+(.+)$", body, re.M)
    return match.group(1).strip() if match else ""


def _description_from_body(body: str) -> str:
    plain = re.sub(r"```.*?```", "", body, flags=re.S)
    plain = re.sub(r"!\[[^\]]*]\([^)]+\)", "", plain)
    plain = re.sub(r"^#+\s*", "", plain, flags=re.M)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:150]


def _infer_taxonomy(body: str, filename: str) -> tuple[list[str], list[str]]:
    text = f"{filename} {body}".lower()
    tags: list[str] = []
    if any(word in text for word in ("数学建模", "mcm", "icm", "modeling")):
        tags.append("数学建模")
    if any(word in text for word in ("python", "matlab", "算法", "模型")):
        tags.append("技术写作")
    if not tags:
        tags.append("博客")
    return ["写作"], tags[:5]


def _detect_language(text: str) -> str:
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return "zh" if cjk / max(len(text), 1) > 0.1 else "en"


def _content_type_to_ext(content_type: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
    }.get(content_type.lower(), "png")
