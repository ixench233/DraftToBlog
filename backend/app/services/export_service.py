from __future__ import annotations

import re
from html import escape
from io import BytesIO
from pathlib import Path
from textwrap import wrap

from docx import Document
from docx.shared import Pt
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def export_document(payload: dict, format_name: str) -> tuple[bytes, str, str]:
    content = payload["processed_content"]
    stem = _safe_stem(payload["filename"])
    if format_name == "markdown":
        return content.encode("utf-8"), f"{stem}.md", "text/markdown; charset=utf-8"
    if format_name == "docx":
        return _to_docx(content), f"{stem}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if format_name == "pdf":
        return _to_pdf(content), f"{stem}.pdf", "application/pdf"
    raise ValueError("导出格式仅支持 markdown、docx 或 pdf。")


def _to_docx(content: str) -> bytes:
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            document.add_paragraph()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
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
        if match:
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

