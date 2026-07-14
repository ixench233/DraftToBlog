"""
合并三篇美赛相关文档为一篇博客。
用法: python merge_mcm.py
"""
from __future__ import annotations
import re
import textwrap
import traceback
from pathlib import Path

from rich.console import Console

from markflow.config import load_config
from markflow.llm.processor import LLMProcessor, _blocks_to_draft, _split_chunks
from markflow.parsers.docx_parser import DocxParser
from markflow.renderer import hexo
from markflow.uploader.cos_uploader import CosUploader

console = Console(highlight=False, force_terminal=True)

FILES = [
    Path("input/mcm/数模美赛论文写作（数据查找、画图）_.docx"),
    Path("input/mcm/数模资料合集 大家找到的都可以放进来.docx"),
    Path("input/mcm/美赛资料汇总.docx"),
]
OUTPUT = Path("output/数模美赛论文写作（数据查找、画图）_.md")


def parse_and_upload(path: Path, cfg, uploader: CosUploader):
    console.rule(f"[bold cyan]解析 {path.name}[/bold cyan]")
    parser = DocxParser()
    doc = parser.parse(path)
    console.print(f"  {len(doc.blocks)} 块  {len(doc.images)} 张图片  语言={doc.detected_lang}")

    for img in doc.images:
        try:
            img.cos_url = uploader.upload(img, path.name)
            console.print(f"  [green]✓[/green] 图片{img.index} → {img.cos_url[:70]}...")
        except Exception as e:
            console.print(f"  [yellow]⚠ 图片{img.index} 上传失败: {e}[/yellow]")
            img.cos_url = ""
    return doc


def rewrite_doc(doc, llm: LLMProcessor, label: str) -> str:
    console.print(f"\n[cyan]LLM 重写：{label}[/cyan]")
    parts: list[str] = []
    for chunk in llm.stream_rewrite(doc):
        console.print(chunk, end="", highlight=False)
        parts.append(chunk)
    console.print()
    return "".join(parts)


def merge_with_llm(sections: list[tuple[str, str]], llm: LLMProcessor) -> str:
    """Ask LLM to merge multiple rewritten sections into one coherent blog post."""
    lang = "zh"
    combined = "\n\n---\n\n".join(
        f"## 来源：{label}\n\n{content}" for label, content in sections
    )
    chunks = _split_chunks(combined, llm._cfg.chunk_size)

    console.print(f"\n[cyan]LLM 融合整合（{len(chunks)} 块）...[/cyan]")
    merged_parts: list[str] = []
    for i, chunk in enumerate(chunks):
        console.print(f"  [dim]融合 chunk {i+1}/{len(chunks)}[/dim]")
        prompt = textwrap.dedent(f"""\
            以下是来自多份文档的内容，请将它们整合为一篇结构清晰、去除重复、逻辑连贯的中文技术博客正文。
            要求：
            - 合并相同主题的内容，去除重复信息，保留各文档的独特补充内容
            - 按主题重新组织章节结构（如：工具推荐、数据查找、论文写作技巧、比赛策略等）
            - 使用博客叙述风格，标题层级清晰（# ## ###）
            - 【强制】保留所有 [IMG_数字] 标记在其对应位置，不得删除
            - 保留代码块、表格格式不变
            - 直接输出 Markdown 正文，不加开场白

            内容：
            {chunk}
        """)
        stream = llm._client.chat.completions.create(
            model=llm._cfg.model,
            temperature=llm._cfg.temperature,
            max_tokens=llm._cfg.chunk_size * 3,
            stream=True,
            messages=[
                {"role": "system", "content": "你是一位技术博客作者，擅长将多份资料整合为结构清晰的博客文章。"},
                {"role": "user", "content": prompt},
            ],
        )
        part = []
        for event in stream:
            delta = event.choices[0].delta.content
            if delta:
                console.print(delta, end="", highlight=False)
                part.append(delta)
        console.print()
        merged_parts.append("".join(part))

    return "\n\n".join(merged_parts)


def inject_images(body: str, all_images) -> str:
    used = set()

    def replacer(m: re.Match) -> str:
        n = int(m.group(1))
        used.add(n)
        img = next((i for i in all_images if i.index == n), None)
        if img:
            url = img.cos_url or f"images/img{n}.{img.ext}"
            alt = img.alt_text or f"图{n+1}"
            return f"![{alt}]({url})"
        return ""

    body = re.sub(r"\[IMG_(\d+)\]", replacer, body)
    return body


def main():
    cfg = load_config()
    llm = LLMProcessor(cfg.llm)
    uploader = CosUploader(cfg)

    if not uploader.is_ready():
        console.print("[red]COS 未配置，图片将跳过上传[/red]")

    # 1. 解析所有文件，上传图片，重写内容
    # 需要对跨文件图片 index 去重 —— 给每个文件的图片分配全局 index
    global_img_offset = 0
    sections: list[tuple[str, str]] = []
    all_images = []

    for path in FILES:
        if not path.exists():
            console.print(f"[yellow]跳过不存在的文件: {path}[/yellow]")
            continue

        doc = parse_and_upload(path, cfg, uploader)

        # 重新分配全局 index，避免不同文件的 IMG_N 冲突
        for img in doc.images:
            img.index = global_img_offset + img.index
        global_img_offset += len(doc.images)
        all_images.extend(doc.images)

        # 重建 blocks_to_draft 使用全局 index
        draft = _make_draft_with_global_index(doc)
        doc._global_draft = draft  # 临时附加

        rewritten = rewrite_doc_from_draft(draft, doc.detected_lang, llm, path.stem)
        sections.append((path.stem, rewritten))

    if not sections:
        console.print("[red]没有可处理的文件[/red]")
        return

    # 2. 用 LLM 融合所有内容
    merged_body = merge_with_llm(sections, llm)

    # 3. 注入图片
    merged_body = inject_images(merged_body, all_images)

    # 4. 生成元数据
    console.print("\n[cyan]生成标题 / 摘要 / 标签...[/cyan]")
    from markflow.models import ParsedDocument, ContentBlock, BlockType
    dummy_doc = ParsedDocument(
        blocks=[ContentBlock(type=BlockType.PARAGRAPH, content=merged_body[:2000])],
        detected_lang="zh"
    )
    titles = llm.generate_titles(dummy_doc)
    title = titles[0] if titles else "数模美赛全攻略"
    console.print(f"  标题：{title}")

    description = llm.generate_description(merged_body, "zh")
    tags, categories = llm.generate_tags_categories(merged_body, "zh")

    # 5. 生成图片 alt text
    console.print("\n[cyan]生成图片描述...[/cyan]")
    for img in all_images:
        if not img.cos_url:
            continue
        context = merged_body[:300]
        img.alt_text = llm.generate_alt_text(img, context, "zh")

    # 6. 渲染输出
    output_md = hexo.render(
        merged_body,
        title=title,
        description=description,
        tags=tags,
        categories=categories,
        images=all_images,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(output_md, encoding="utf-8")
    console.print(f"\n[bold green]✓ 已写入：{OUTPUT}[/bold green]")


def _make_draft_with_global_index(doc) -> str:
    """Like _blocks_to_draft but uses the globally-reassigned img.index."""
    from markflow.models import BlockType
    parts = []
    for b in doc.blocks:
        if b.type == BlockType.IMAGE and b.image:
            parts.append(f"[IMG_{b.image.index}]")
        elif b.type == BlockType.HEADING:
            parts.append("#" * b.level + " " + b.content)
        elif b.type == BlockType.CODE:
            parts.append(f"```\n{b.content}\n```")
        elif b.type == BlockType.TABLE:
            parts.append(b.content)
        else:
            parts.append(b.content)
    return "\n\n".join(p for p in parts if p)


def rewrite_doc_from_draft(draft: str, lang: str, llm: LLMProcessor, label: str) -> str:
    chunks = _split_chunks(draft, llm._cfg.chunk_size)
    console.print(f"\n[cyan]LLM 重写 [{label}]（{len(chunks)} 块）...[/cyan]")
    parts = []
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            console.print(f"  [dim]chunk {i+1}/{len(chunks)}[/dim]")
        for token in llm._stream_chunk(chunk, lang):
            console.print(token, end="", highlight=False)
            parts.append(token)
        console.print()
    return "".join(parts)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
