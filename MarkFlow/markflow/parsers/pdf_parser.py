from __future__ import annotations
import hashlib
import re
from pathlib import Path

import pdfplumber
import fitz  # PyMuPDF

from markflow.models import BlockType, ContentBlock, ImageBlock, ParsedDocument
from markflow.parsers.base import BaseParser


class PdfParser(BaseParser):
    EXTENSIONS = {".pdf"}

    def parse(self, path: Path) -> ParsedDocument:
        blocks: list[ContentBlock] = []
        images: list[ImageBlock] = []
        seen_md5: dict[str, int] = {}

        mupdf = fitz.open(str(path))

        with pdfplumber.open(str(path)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                # Extract text blocks with positional info
                page_blocks = page.extract_words(
                    x_tolerance=3,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    use_text_flow=True,
                    extra_attrs=["size", "fontname"],
                )
                if not page_blocks:
                    continue

                text_blocks = self._group_into_lines(page, page_blocks)
                for tb in text_blocks:
                    block = self._classify_block(tb)
                    if block:
                        blocks.append(block)

                # Extract images from this page via PyMuPDF
                mupdf_page = mupdf[page_num]
                for img_info in mupdf_page.get_images(full=True):
                    xref = img_info[0]
                    img_data = mupdf.extract_image(xref)
                    data = img_data["image"]
                    ext = img_data.get("ext", "png")
                    if ext == "jpeg":
                        ext = "jpg"

                    md5 = hashlib.md5(data).hexdigest()
                    if md5 in seen_md5:
                        continue
                    if len(data) < 1024:  # skip tiny images (bullets, icons)
                        continue

                    idx = len(seen_md5)
                    seen_md5[md5] = idx
                    img_block = ImageBlock(
                        index=idx,
                        data=data,
                        ext=ext,
                        md5=md5,
                        paragraph_idx=len(blocks),
                    )
                    images.append(img_block)
                    blocks.append(ContentBlock(type=BlockType.IMAGE, image=img_block))

        mupdf.close()

        # Build table blocks from pdfplumber table extraction (separate pass)
        table_blocks = self._extract_tables(path)
        # Append tables at the end; a more precise position merge is a future improvement
        blocks.extend(table_blocks)

        detected_lang = _detect_lang(blocks)
        title_hint = _guess_title(blocks)

        return ParsedDocument(
            blocks=blocks,
            images=images,
            detected_lang=detected_lang,
            title_hint=title_hint,
        )

    def _group_into_lines(self, page, words: list[dict]) -> list[dict]:
        """Group word dicts into line-level dicts with aggregated text and avg font size."""
        if not words:
            return []

        lines: list[dict] = []
        current_line: list[dict] = [words[0]]

        for word in words[1:]:
            prev = current_line[-1]
            # Same line if vertical midpoint is within 3 pts
            if abs(word["top"] - prev["top"]) < 6:
                current_line.append(word)
            else:
                lines.append(_merge_line(current_line))
                current_line = [word]
        lines.append(_merge_line(current_line))
        return lines

    def _classify_block(self, line: dict) -> ContentBlock | None:
        text = line["text"].strip()
        if not text:
            return None

        size = line.get("size", 12)
        fontname = (line.get("fontname", "") or "").lower()

        is_bold = "bold" in fontname or "black" in fontname
        is_mono = any(f in fontname for f in ("mono", "courier", "consol", "code"))

        if is_mono:
            return ContentBlock(type=BlockType.CODE, content=text)

        if size >= 18 or (size >= 15 and is_bold):
            return ContentBlock(type=BlockType.HEADING, content=text, level=1)
        if size >= 14 or (size >= 12 and is_bold):
            return ContentBlock(type=BlockType.HEADING, content=text, level=2)
        if size >= 12 and is_bold:
            return ContentBlock(type=BlockType.HEADING, content=text, level=3)

        # Bullet list heuristic
        if re.match(r"^[•·▪▸➢\-\*]\s+", text) or re.match(r"^\d+[.)]\s+", text):
            return ContentBlock(type=BlockType.LIST, content="- " + re.sub(r"^[•·▪▸➢\-\*\d.)]+\s+", "", text))

        return ContentBlock(type=BlockType.PARAGRAPH, content=text)

    def _extract_tables(self, path: Path) -> list[ContentBlock]:
        results: list[ContentBlock] = []
        try:
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    for table in page.extract_tables():
                        if not table:
                            continue
                        lines: list[str] = []
                        for i, row in enumerate(table):
                            cells = [str(c or "").replace("\n", " ") for c in row]
                            lines.append("| " + " | ".join(cells) + " |")
                            if i == 0:
                                lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
                        results.append(ContentBlock(type=BlockType.TABLE, content="\n".join(lines)))
        except Exception:
            pass
        return results


def _merge_line(words: list[dict]) -> dict:
    text = " ".join(w["text"] for w in words)
    sizes = [w.get("size", 12) for w in words if w.get("size")]
    avg_size = sum(sizes) / len(sizes) if sizes else 12
    fontname = words[0].get("fontname", "") if words else ""
    top = words[0].get("top", 0) if words else 0
    return {"text": text, "size": avg_size, "fontname": fontname, "top": top}


def _detect_lang(blocks: list[ContentBlock]) -> str:
    sample = " ".join(b.content for b in blocks[:30] if b.content)[:500]
    cjk = sum(1 for c in sample if "一" <= c <= "鿿")
    return "zh" if cjk / max(len(sample), 1) > 0.1 else "en"


def _guess_title(blocks: list[ContentBlock]) -> str:
    for b in blocks[:5]:
        if b.type == BlockType.HEADING and b.level == 1 and b.content:
            return b.content
    return ""
