from __future__ import annotations
import hashlib
import io
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from markflow.models import BlockType, ContentBlock, ImageBlock, ParsedDocument
from markflow.parsers.base import BaseParser


class DocxParser(BaseParser):
    EXTENSIONS = {".docx"}

    def parse(self, path: Path) -> ParsedDocument:
        doc = Document(str(path))
        blocks: list[ContentBlock] = []
        images: list[ImageBlock] = []
        seen_md5: dict[str, int] = {}  # md5 -> image index for dedup

        para_idx = 0
        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                para = Paragraph(element, doc)
                block, img = self._parse_paragraph(para, para_idx, seen_md5, doc)
                if img:
                    images.append(img)
                if block:
                    blocks.append(block)
                para_idx += 1

            elif tag == "tbl":
                tbl = Table(element, doc)
                block = self._parse_table(tbl)
                if block:
                    blocks.append(block)

        title_hint = _extract_title(doc)
        detected_lang = _detect_lang_hint(doc)
        return ParsedDocument(
            blocks=blocks,
            images=images,
            detected_lang=detected_lang,
            title_hint=title_hint,
        )

    def _parse_paragraph(
        self,
        para: Paragraph,
        para_idx: int,
        seen_md5: dict[str, int],
        doc: Document,
    ) -> tuple[ContentBlock | None, ImageBlock | None]:
        # Check for inline image first
        img_block = self._extract_image(para, para_idx, seen_md5, doc)
        if img_block is not None:
            return ContentBlock(type=BlockType.IMAGE, image=img_block), img_block

        text = para.text.strip()
        if not text:
            return None, None

        style_name = (para.style.name if para.style else "").lower()

        # Heading detection
        if style_name.startswith("heading"):
            try:
                level = int(style_name.split()[-1])
            except ValueError:
                level = 1
            level = min(max(level, 1), 4)
            return ContentBlock(type=BlockType.HEADING, content=text, level=level), None

        # Code block heuristic: monospace style or indented with no punctuation
        if "code" in style_name or style_name in ("macro text", "html preformatted"):
            return ContentBlock(type=BlockType.CODE, content=text), None

        # List detection
        if para.style and para.style.name and "list" in style_name:
            prefix = "- "
            try:
                num_fmt = para._p.find(qn("w:numPr"))
                if num_fmt is not None:
                    prefix = "1. "
            except Exception:
                pass
            return ContentBlock(type=BlockType.LIST, content=prefix + text), None

        return ContentBlock(type=BlockType.PARAGRAPH, content=text), None

    def _extract_image(
        self,
        para: Paragraph,
        para_idx: int,
        seen_md5: dict[str, int],
        doc: Document,
    ) -> ImageBlock | None:
        # Look for drawing / inline image XML elements
        drawing = para._p.find(".//" + qn("a:blip"))
        if drawing is None:
            return None

        r_embed = drawing.get(qn("r:embed"))
        if not r_embed:
            return None

        try:
            image_part = doc.part.related_parts[r_embed]
            data = image_part.blob
        except (KeyError, Exception):
            return None

        md5 = hashlib.md5(data).hexdigest()
        if md5 in seen_md5:
            # Duplicate — return existing image reference wrapped in a block
            existing_idx = seen_md5[md5]
            # We still need to return something that references the existing image
            return None  # caller will skip adding to images list

        ext = _content_type_to_ext(image_part.content_type)
        idx = len(seen_md5)
        seen_md5[md5] = idx
        return ImageBlock(
            index=idx,
            data=data,
            ext=ext,
            md5=md5,
            paragraph_idx=para_idx,
        )

    def _parse_table(self, tbl: Table) -> ContentBlock | None:
        rows = tbl.rows
        if not rows:
            return None

        lines: list[str] = []
        for i, row in enumerate(rows):
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("| " + " | ".join(["---"] * len(cells)) + " |")

        return ContentBlock(type=BlockType.TABLE, content="\n".join(lines))


def _extract_title(doc: Document) -> str:
    for para in doc.paragraphs:
        style = (para.style.name if para.style else "").lower()
        if style == "title" or style.startswith("heading 1"):
            text = para.text.strip()
            if text:
                return text
    return ""


def _detect_lang_hint(doc: Document) -> str:
    """Sample the first 500 chars to guess CJK vs Latin."""
    sample = ""
    for para in doc.paragraphs[:20]:
        sample += para.text
        if len(sample) > 500:
            break
    cjk = sum(1 for c in sample if "一" <= c <= "鿿")
    return "zh" if cjk / max(len(sample), 1) > 0.1 else "en"


def _content_type_to_ext(ct: str) -> str:
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
    }
    return mapping.get(ct.lower(), "png")
