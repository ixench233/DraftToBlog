from __future__ import annotations

import re
import httpx
from concurrent.futures import ThreadPoolExecutor
from html import escape
from io import BytesIO
from pathlib import Path
from textwrap import wrap

from docx import Document
from docx.shared import Pt
from docx.shared import Inches
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from .blog_service import normalize_published_markdown, render_blog_markdown, title_stem_from_markdown


MARKDOWN_IMAGE = re.compile(r"^!\[([^]]*)\]\((https?://[^)]+)\)$")


def export_document(payload: dict, format_name: str) -> tuple[bytes, str, str]:
    content = normalize_published_markdown(payload["processed_content"])
    stem = title_stem_from_markdown(content, payload["filename"])
    if format_name == "markdown":
        return content.encode("utf-8"), f"{stem}.md", "text/markdown; charset=utf-8"
    if format_name == "hexo":
        blog = render_blog_markdown(content, payload["filename"], payload.get("assets", []), "hexo")
        return blog.encode("utf-8"), f"{stem}.hexo.md", "text/markdown; charset=utf-8"
    if format_name == "hugo":
        blog = render_blog_markdown(content, payload["filename"], payload.get("assets", []), "hugo")
        return blog.encode("utf-8"), f"{stem}.hugo.md", "text/markdown; charset=utf-8"
    if format_name == "astro":
        blog = render_blog_markdown(content, payload["filename"], payload.get("assets", []), "astro")
        return blog.encode("utf-8"), f"{stem}.astro.md", "text/markdown; charset=utf-8"
    if format_name == "docx":
        return _to_docx(content), f"{stem}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if format_name == "pdf":
        return _to_pdf(content), f"{stem}.pdf", "application/pdf"
    raise ValueError("导出格式仅支持 markdown、docx 或 pdf。")


def _to_docx(content: str) -> bytes:
    document = Document()
    downloaded_images = _download_images(content)
    normal = document.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            document.add_paragraph()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        image = MARKDOWN_IMAGE.match(stripped)
        if image and (image_bytes := downloaded_images.get(image.group(2))):
            document.add_picture(BytesIO(image_bytes), width=Inches(6))
            if image.group(1):
                document.add_paragraph(image.group(1))
        elif heading:
            document.add_heading(heading.group(2), level=min(len(heading.group(1)), 4))
        elif stripped.startswith("> "):
            document.add_paragraph(stripped[2:], style="Quote")
        elif stripped.startswith(('- ', '* ')):
            document.add_paragraph(stripped[2:], style="List Bullet")
        else:
            document.add_paragraph(stripped)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _to_pdf(content: str) -> bytes:
    output = BytesIO()
    downloaded_images = _download_images(content)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="DraftToBlog Export",
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "ChineseBody",
        parent=styles["BodyText"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=17,
        alignment=TA_LEFT,
        spaceAfter=7,
    )
    title = ParagraphStyle(
        "ChineseTitle",
        parent=body,
        fontSize=20,
        leading=28,
        spaceAfter=14,
    )
    heading = ParagraphStyle(
        "ChineseHeading",
        parent=body,
        fontSize=14,
        leading=21,
        spaceBefore=10,
        spaceAfter=8,
    )
    story = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 4))
            continue
        match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        image = MARKDOWN_IMAGE.match(stripped)
        if image and (image_bytes := downloaded_images.get(image.group(2))):
            graphic = Image(BytesIO(image_bytes))
            graphic._restrictSize(170 * mm, 210 * mm)
            story.append(graphic)
            if image.group(1):
                story.append(Paragraph(escape(image.group(1)), body))
        elif match:
            style = title if len(match.group(1)) == 1 else heading
            story.append(Paragraph(escape(match.group(2)), style))
        else:
            safe = escape(stripped.removeprefix("> "))
            story.append(Paragraph(safe, body))
    document.build(story)
    return output.getvalue()


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", stem).strip("-") or "draft-to-blog"


def _download_image(url: str) -> bytes | None:
    try:
        response = httpx.get(url, timeout=20, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except httpx.HTTPError:
        return None


def _download_images(content: str) -> dict[str, bytes]:
    urls = list(dict.fromkeys(match.group(2) for match in map(MARKDOWN_IMAGE.match, content.splitlines()) if match))
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as executor:
        values = list(executor.map(_download_image, urls))
    return {url: value for url, value in zip(urls, values) if value is not None}
