from app.services.blog_service import normalize_published_markdown, render_blog_markdown
from app.services.export_service import export_document


def test_export_cleanup_removes_artifacts_and_normalizes_headings() -> None:
    content = """# 数模美赛论文写作指南

# 数模美赛论文写作指南（第二部分）

draft-to-blog://IMG_placeholder

注：此部分内容在原文中仅为标题。

*   **Excel*：用于数据分析。

![image](https://cdn.example.com/a.png)

![image again](https://cdn.example.com/a.png)

# 模型假设（第三部分）

正文
"""
    cleaned = normalize_published_markdown(content)
    assert "第二部分" not in cleaned
    assert "第三部分" not in cleaned
    assert "draft-to-blog://" not in cleaned
    assert "此部分内容" not in cleaned
    assert cleaned.count("\n# ") == 0
    assert cleaned.count("https://cdn.example.com/a.png") == 1
    assert "## 数模美赛论文写作指南" in cleaned
    assert "**Excel**" in cleaned


def test_blog_export_uses_title_based_filename_with_format_suffix() -> None:
    payload = {
        "filename": "draft-to-blog.docx",
        "processed_content": "# 数模美赛论文写作指南\n\n正文",
        "assets": [],
    }
    _, filename, _ = export_document(payload, "hexo")
    assert filename == "数模美赛论文写作指南.hexo.md"


def test_description_is_plain_text_without_markdown_or_images() -> None:
    content = """# 标题

![image](https://cdn.example.com/a.png)

* **Excel**：用于数据分析。

| A | B |
| --- | --- |
"""
    rendered = render_blog_markdown(content, "draft.md", [], "hexo")
    front_matter = rendered.split("---", 2)[1]
    assert "![" not in front_matter
    assert "**" not in front_matter
    assert "|" not in front_matter


def test_description_summarizes_article_as_a_whole() -> None:
    content = """# 数模美赛论文写作指南

数模美赛论文写作指南

数据分析与可视化

Excel：用于数据分析。

写作框架

Summary Sheet（摘要页）
"""
    rendered = render_blog_markdown(content, "draft.md", [], "hexo")
    front_matter = rendered.split("---", 2)[1]
    assert "本文围绕《数模美赛论文写作指南》" in front_matter
    assert "数据分析与可视化" in front_matter
    assert "Excel：用于数据分析" not in front_matter


def test_cleanup_removes_draft_to_blog_footer() -> None:
    content = """# 标题

正文

---

> 本文由 DraftToBlog 完成格式整理与隐私检查，请在发布前人工复核。"""
    cleaned = normalize_published_markdown(content)
    assert "DraftToBlog" not in cleaned
    assert not cleaned.rstrip().endswith("---")


def test_export_cleanup_removes_internal_image_tokens() -> None:
    cleaned = normalize_published_markdown("before\n\n@@DTBIMAGE8:@@\n\nafter")

    assert "@@DTBIMAGE" not in cleaned
