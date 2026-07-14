# MarkFlow — PRD（产品需求文档）

> 版本：v0.2  日期：2026-05-14  状态：需求已确认，待开发

---

## 1. 产品概述

MarkFlow 是一个命令行工具，将 PDF / Word 文档转换为高质量的 Markdown 博客文章。转换过程中，文档内的图片自动提取并上传至腾讯云 COS，最终生成的 Markdown 文件中引用可公开访问的云端图片链接。大模型（LLM）负责内容大幅压缩重组、结构优化和标题生成，输出物符合 **Hexo Butterfly 主题**的博客规范，可直接放入 `source/_posts/` 目录发布。

目标博客：**沉汐 DevLog**（https://chenxi34.github.io），Hexo + Butterfly v5.5.1。

---

## 2. 目标用户

- 需要将技术文档、研究报告、PPT 讲义批量转为博客的工程师或研究者
- 内容创作者，希望把已有 Word 草稿快速发布到 Hexo 博客

---

## 3. 核心功能需求

### 3.1 文件输入

| 需求编号 | 描述 |
|----------|------|
| F-01 | 支持单文件输入：`markflow input.pdf` |
| F-02 | 支持多文件批量输入：`markflow a.pdf b.docx c.pdf` |
| F-03 | 支持目录批量扫描：`markflow --dir ./docs` |
| F-04 | 支持 PDF（含扫描版 OCR 降级处理）和 Word（`.docx`）格式 |

### 3.2 内容解析

| 需求编号 | 描述 |
|----------|------|
| F-05 | 提取文档正文文本，保留段落、标题层级（H1~H4）、列表、表格结构 |
| F-06 | 提取文档内所有嵌入图片，按出现顺序编号，保留原始格式（PNG / JPEG） |
| F-07 | 记录每张图片在文档中的相对位置（段落索引），用于 Markdown 中精准插图 |
| F-08 | 对扫描版 PDF（无文字层），调用 OCR 引擎（Tesseract 或云端 OCR）提取文字（MVP 后实现） |

### 3.3 图片上云（腾讯云 COS + PicGo）

| 需求编号 | 描述 |
|----------|------|
| F-09 | 读取 PicGo 配置文件（`~/.picgo/config.json`）获取腾讯云 COS 凭据（SecretId、SecretKey、Bucket、Region） |
| F-10 | 将提取的图片上传至配置的 COS Bucket，路径格式：`markflow/{year}/{month}/{原始文件名-hash8}.{ext}` |
| F-11 | 上传成功后返回公网可访问 URL，作为 `![alt](url)` 中的图片地址 |
| F-12 | 支持自定义 CDN 域名（配置项 `cdn_domain`），替换默认 COS 域名 |
| F-13 | 图片上传失败时，将图片保存至本地 `output/images/` 并使用相对路径，同时打印警告 |
| F-14 | 支持去重：对同一文档中重复图片（MD5 相同）只上传一次 |

### 3.4 大模型内容处理

| 需求编号 | 描述 |
|----------|------|
| F-15 | 支持配置 LLM API（默认兼容 OpenAI 格式，支持 Claude / DeepSeek / 本地 Ollama 等） |
| F-16 | LLM 任务 1 — 博客标题生成：根据文档内容生成 1~3 个候选标题，用户可选或使用默认第一个 |
| F-17 | LLM 任务 2 — 内容大幅压缩重组：允许对原文进行大幅压缩与重组，以博客叙述风格重新组织内容，保留核心技术细节，删除冗余铺垫，优化段落节奏 |
| F-18 | LLM 任务 3 — description 生成：生成 80~150 字摘要，填入 Hexo Front Matter 的 `description` 字段 |
| F-19 | LLM 任务 4 — 标签 / 分类推荐：输出 3~5 个 `tags` 和 1~2 个 `categories`，填入 Front Matter |
| F-20 | LLM 任务 5 — 图片 alt text 生成：结合图片在文档中的上下文，为每张图片生成一句描述性 alt text |
| F-21 | 支持 `--no-llm` 模式：跳过 LLM 处理，仅做格式转换 |
| F-22 | LLM 调用支持流式输出，终端实时展示进度 |
| F-23 | 超长文档自动分块（chunk_size 可配置，默认 3000 token），分块处理后合并 |
| F-24 | LLM prompt 根据检测到的文档语言自动切换（中文文档 → 中文博客，英文文档 → 英文博客） |

### 3.5 Markdown 输出（Hexo Butterfly 格式）

| 需求编号 | 描述 |
|----------|------|
| F-25 | 输出标准 Markdown 文件，包含 Hexo Butterfly 主题的 YAML Front Matter（见下方格式说明） |
| F-26 | 图片以 `![LLM生成的alt文字](cos-url)` 格式嵌入，位置与原文档一致 |
| F-27 | 表格转换为 GFM 表格格式 |
| F-28 | 代码块自动识别并添加语言标注（如 ` ```python ` ） |
| F-29 | 输出文件默认命名为 `{原文件名}.md`，可通过 `--output` 指定路径 |
| F-30 | 批量处理时输出至 `./output/` 目录，结构与输入目录保持一致 |
| F-31 | 支持 `--preset hexo`（默认）和 `--preset hugo` 切换 Front Matter 格式 |

---

## 4. Hexo Butterfly Front Matter 格式规范

输出的 Markdown 文件头部必须符合以下格式（基于对 chenxi34.github.io 博客的分析）：

```yaml
---
title: 文章标题（LLM 生成）
date: 2026-05-14 10:00:00
updated: 2026-05-14 10:00:00
tags:
  - 标签1
  - 标签2
  - 标签3
categories:
  - 分类1
description: 文章摘要，80~150字，由 LLM 生成，显示在博客卡片和 SEO description 中
cover: https://cos-url/markflow/2026/05/cover-image.jpg  # 文档第一张图，若无图则省略
---
```

**字段说明：**
- `title`：LLM 生成的博客标题
- `date`：执行转换时的当前时间
- `updated`：同 `date`
- `tags`：LLM 推荐，3~5 个
- `categories`：LLM 推荐，1~2 个
- `description`：LLM 生成的摘要（Butterfly 用此字段作卡片摘要和 meta description）
- `cover`：文档中第一张图片的 COS URL；若文档无图则不生成此字段

**Hugo Front Matter 格式（`--preset hugo`）：**

```yaml
---
title: "文章标题"
date: 2026-05-14T10:00:00+08:00
lastmod: 2026-05-14T10:00:00+08:00
tags: ["标签1", "标签2"]
categories: ["分类1"]
description: "文章摘要"
cover:
  image: "https://cos-url/markflow/2026/05/cover-image.jpg"
---
```

---

## 5. 配置文件

工具使用 `~/.markflow/config.yaml` 作为全局配置（可通过 `--config` 覆盖）：

```yaml
# 腾讯云 COS / PicGo
picgo_config: ~/.picgo/config.json   # 复用 PicGo 已有配置
cdn_domain: ""                        # 可选：自定义 CDN 域名

# LLM
llm:
  provider: openai                    # openai | anthropic | deepseek | ollama
  api_key: sk-xxx
  base_url: https://api.openai.com/v1
  model: gpt-4o
  temperature: 0.7
  chunk_size: 3000                    # 单次 LLM 请求最大 token 数

# 输出
output_dir: ./output
preset: hexo                          # hexo | hugo
```

---

## 6. 命令行界面（CLI）

```
用法：
  markflow <文件...>                  转换一个或多个文件
  markflow --dir <目录>               批量转换目录下所有 PDF/DOCX
  markflow --config <路径>            指定配置文件
  markflow --no-llm                   跳过 LLM，仅做格式转换
  markflow --output <路径>            指定输出路径（单文件模式）
  markflow --model <模型名>           临时覆盖 LLM 模型
  markflow --preset hexo|hugo         覆盖 Front Matter 格式
  markflow init                       交互式初始化配置文件
  markflow --version                  显示版本
```

---

## 7. 处理流程

```
输入文件（PDF / DOCX）
   │
   ▼
[解析器] 提取结构化文本块 + 图片列表（含位置索引）
   │                         │
   │                         ▼
   │                 [图片上传器]
   │                 MD5 去重 → 上传腾讯云 COS
   │                 返回 {图片索引: COS URL} 映射
   │                         │
   ▼                         ▼
[草稿组装] 将文本块与图片 URL 按位置合并为 Markdown 草稿
   │
   ▼
[LLM 流水线]（可跳过）
   ├─ 语言检测
   ├─ 内容大幅压缩重组 → 正文
   ├─ 标题候选生成（交互选择）
   ├─ description 生成（80~150字）
   ├─ tags + categories 推荐
   └─ 图片 alt text 生成（每张图单独一次调用）
   │
   ▼
[Front Matter 组装] 按 preset（hexo/hugo）格式生成头部
   │
   ▼
[输出] 写入 .md 文件
```

---

## 8. 技术选型

| 模块 | 方案 |
|------|------|
| 语言 | Python 3.11+ |
| PDF 解析 | `pdfplumber`（文字层）+ `PyMuPDF`（图片提取） |
| Word 解析 | `python-docx` |
| OCR（降级，MVP 后） | `pytesseract` 或 腾讯云 OCR API |
| 图片上传 | `cos-python-sdk-v5`（腾讯云官方 SDK），读取 PicGo `config.json` |
| LLM 调用 | `openai` Python SDK（兼容 OpenAI 格式的所有 provider） |
| CLI 框架 | `typer` + `rich`（进度条、彩色输出、交互选择） |
| 配置管理 | `pydantic-settings` + YAML |
| 打包 | `pyproject.toml` + `pipx` 安装 |

---

## 9. 非功能需求

- **性能**：单个 50 页 PDF（含 10 张图）处理时间 < 2 分钟（LLM 调用时间取决于网络）
- **可靠性**：图片上传失败降级为本地路径，不中断整体流程
- **可扩展性**：解析器和上传器通过抽象基类实现，便于后续接入 S3 / 阿里云 OSS 等
- **隐私**：API Key 不写入日志，终端输出时脱敏

---

## 10. MVP 范围（第一版）

**包含：**
- DOCX 解析 + 图片提取
- PDF 解析 + 图片提取（非扫描版）
- 腾讯云 COS 上传（读取 PicGo 配置）
- LLM 内容重组 + 标题 + description + tags/categories + 图片 alt text
- Hexo Butterfly Front Matter 输出（`--preset hexo` 默认）
- Hugo Front Matter 输出（`--preset hugo`）
- 单文件 & 多文件 CLI
- `markflow init` 交互式配置向导

**暂不包含（后续迭代）：**
- 扫描版 PDF OCR
- Web UI
- 插件系统
- GitHub Actions 自动发布到 Hexo 仓库

---

## 11. 已确认决策

| # | 问题 | 决策 |
|---|------|------|
| Q1 | LLM 润色程度 | **允许大幅压缩/重组**，保留核心技术细节 |
| Q2 | 博客语言 | **跟随原文档语言**，LLM 自动检测并切换 prompt |
| Q3 | Front Matter 格式 | **Hexo 默认，支持 `--preset hugo` 切换** |
| Q4 | 图片 alt text | **LLM 根据上下文生成描述性 alt text** |
