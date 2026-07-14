from __future__ import annotations
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from markflow.config import AppConfig
from markflow.llm.processor import LLMProcessor, _blocks_to_draft
from markflow.models import BlockType, ContentBlock, ImageBlock, ParsedDocument
from markflow.parsers.docx_parser import DocxParser
from markflow.parsers.pdf_parser import PdfParser
from markflow.renderer import hexo, hugo
from markflow.uploader.cos_uploader import CosUploader

console = Console(highlight=False, force_terminal=True, force_jupyter=False)

_PARSERS = [DocxParser(), PdfParser()]


def process_file(
    path: Path,
    cfg: AppConfig,
    *,
    no_llm: bool = False,
    preset: str | None = None,
    model_override: str | None = None,
    output_path: Path | None = None,
    interactive: bool = True,
) -> Path:
    """Full pipeline for a single file. Returns path to written .md file."""
    preset = preset or cfg.preset

    # --- 1. Parse ---
    parser = next((p for p in _PARSERS if p.supports(path)), None)
    if parser is None:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    with Progress(SpinnerColumn("line"), TextColumn("{task.description}"), console=console) as prog:
        t = prog.add_task(f"[cyan]解析 {path.name}...", total=None)
        doc = parser.parse(path)
        prog.update(t, description=f"[green]✓ 解析完成 ({len(doc.blocks)} 块, {len(doc.images)} 张图片)")
        prog.stop_task(t)

    console.print(f"  语言检测: [bold]{doc.detected_lang}[/bold]")

    # --- 2. Upload images ---
    uploader = CosUploader(cfg)
    if doc.images:
        if not uploader.is_ready():
            console.print("[yellow]⚠ COS 未配置，图片将保存到本地[/yellow]")
        _upload_images(doc, uploader, path, cfg, output_path)

    # --- 3. LLM pipeline ---
    if no_llm:
        console.print("[dim]跳过 LLM（--no-llm）[/dim]")
        rewritten = _blocks_to_markdown(doc)
        title = doc.title_hint or path.stem
        description = ""
        tags: list[str] = []
        categories: list[str] = []
    else:
        if model_override:
            cfg.llm.model = model_override
        llm = LLMProcessor(cfg.llm)
        rewritten, title, description, tags, categories = _run_llm(
            llm, doc, path, interactive=interactive
        )

    # --- 4. Inject image alt texts into rewritten body ---
    rewritten = _inject_images(rewritten, doc.images)

    # --- 5. Render ---
    render_fn = hexo.render if preset == "hexo" else hugo.render
    output_md = render_fn(
        rewritten,
        title=title,
        description=description,
        tags=tags,
        categories=categories,
        images=doc.images,
    )

    # --- 6. Write output ---
    out = _resolve_output(path, output_path, cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(output_md, encoding="utf-8")
    console.print(f"[bold green]✓ 已写入:[/bold green] {out}")
    return out


# ------------------------------------------------------------------
# Image upload
# ------------------------------------------------------------------

def _upload_images(
    doc: ParsedDocument,
    uploader: CosUploader,
    source: Path,
    cfg: AppConfig,
    output_path: Path | None,
) -> None:
    local_dir = _local_image_dir(source, output_path, cfg)
    with Progress(SpinnerColumn("line"), TextColumn("{task.description}"), console=console) as prog:
        for img in doc.images:
            t = prog.add_task(f"上传图片 {img.index + 1}/{len(doc.images)}...", total=None)
            if uploader.is_ready():
                try:
                    img.cos_url = uploader.upload(img, source.name)
                    prog.update(t, description=f"[green]✓ 图片 {img.index + 1} → {img.cos_url[:60]}...")
                except Exception as e:
                    console.print(f"[yellow]⚠ 图片 {img.index + 1} 上传失败: {e}，保存本地[/yellow]")
                    img.cos_url = _save_local(img, source, local_dir)
            else:
                img.cos_url = _save_local(img, source, local_dir)
            prog.stop_task(t)


def _save_local(img: ImageBlock, source: Path, local_dir: Path) -> str:
    local_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{source.stem}-img{img.index + 1}.{img.ext}"
    dest = local_dir / fname
    dest.write_bytes(img.data)
    return f"images/{fname}"


def _local_image_dir(source: Path, output_path: Path | None, cfg: AppConfig) -> Path:
    if output_path:
        return output_path.parent / "images"
    return cfg.output_dir / "images"


# ------------------------------------------------------------------
# LLM
# ------------------------------------------------------------------

def _run_llm(
    llm: LLMProcessor,
    doc: ParsedDocument,
    path: Path,
    interactive: bool,
) -> tuple[str, str, str, list[str], list[str]]:
    lang = doc.detected_lang

    # Task 2: rewrite (streaming to terminal)
    console.print("[cyan]正文重组中...[/cyan]")
    rewritten_parts: list[str] = []
    for chunk in llm.stream_rewrite(doc):
        console.print(chunk, end="", highlight=False)
        rewritten_parts.append(chunk)
    rewritten = "".join(rewritten_parts)
    console.print()

    # Task 5: image alt texts
    if doc.images:
        console.print("[cyan]生成图片描述...[/cyan]")
        for img in doc.images:
            context = _image_context(doc, img)
            img.alt_text = llm.generate_alt_text(img, context, lang)

    # Task 1: titles
    console.print("[cyan]生成标题候选...[/cyan]")
    titles = llm.generate_titles(doc)

    if interactive and titles and sys.stdin.isatty():
        title = _pick_title(titles, path.stem)
    else:
        title = titles[0] if titles else doc.title_hint or path.stem

    # Tasks 3 & 4
    console.print("[cyan]生成摘要和标签...[/cyan]")
    description = llm.generate_description(rewritten, lang)
    tags, categories = llm.generate_tags_categories(rewritten, lang)

    return rewritten, title, description, tags, categories


def _pick_title(titles: list[str], fallback: str) -> str:
    console.print("\n[bold]候选标题：[/bold]")
    for i, t in enumerate(titles, 1):
        console.print(f"  {i}. {t}")
    console.print(f"  0. 自定义")
    raw = console.input("\n选择标题编号（回车使用第1个）: ").strip()
    if raw == "0":
        return console.input("输入自定义标题: ").strip() or fallback
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(titles):
            return titles[idx]
    except ValueError:
        pass
    return titles[0]


def _image_context(doc: ParsedDocument, img: ImageBlock) -> str:
    """Get text surrounding the image's paragraph index."""
    para_idx = img.paragraph_idx
    parts: list[str] = []
    for b in doc.blocks:
        if b.type != BlockType.IMAGE and b.content:
            parts.append(b.content)
    # Return up to 200 chars around the image position
    all_text = " ".join(parts)
    return all_text[:300]


# ------------------------------------------------------------------
# Markdown assembly (no-LLM path)
# ------------------------------------------------------------------

def _blocks_to_markdown(doc: ParsedDocument) -> str:
    parts: list[str] = []
    for b in doc.blocks:
        if b.type == BlockType.IMAGE and b.image:
            img = b.image
            url = img.cos_url or f"images/{img.index + 1}.{img.ext}"
            alt = img.alt_text or f"图{img.index + 1}"
            parts.append(f"![{alt}]({url})")
        elif b.type == BlockType.HEADING:
            parts.append("#" * b.level + " " + b.content)
        elif b.type == BlockType.CODE:
            lang = b.language or ""
            parts.append(f"```{lang}\n{b.content}\n```")
        elif b.type == BlockType.TABLE:
            parts.append(b.content)
        elif b.type == BlockType.LIST:
            parts.append(b.content)
        else:
            parts.append(b.content)
    return "\n\n".join(p for p in parts if p)


# ------------------------------------------------------------------
# Image placeholder injection into LLM-rewritten body
# ------------------------------------------------------------------

def _inject_images(body: str, images: list[ImageBlock]) -> str:
    """Replace [IMG_N] placeholders with actual Markdown image syntax.

    Handles two cases:
    - LLM preserved placeholders → replace each [IMG_N] in-place (correct position)
    - LLM dropped placeholders → fall back to appending at end
    """
    if not images:
        return body

    def _md(img: ImageBlock) -> str:
        url = img.cos_url or f"images/{img.index + 1}.{img.ext}"
        alt = img.alt_text or f"图{img.index + 1}"
        return f"![{alt}]({url})"

    used = set()

    def replacer(m: re.Match) -> str:
        n = int(m.group(1))
        used.add(n)
        if n < len(images):
            return _md(images[n])
        return ""

    # Match [IMG_0], [IMG_1], ... produced by _blocks_to_draft
    body = re.sub(r"\[IMG_(\d+)\]", replacer, body)

    # Append any images the LLM silently dropped
    missed = [img for img in images if img.index not in used]
    if missed:
        extra = "\n\n".join(_md(img) for img in missed)
        body = body.rstrip() + "\n\n" + extra

    return body


# ------------------------------------------------------------------
# Output path resolution
# ------------------------------------------------------------------

def _resolve_output(source: Path, output_path: Path | None, cfg: AppConfig) -> Path:
    if output_path:
        return output_path
    return cfg.output_dir / (source.stem + ".md")
