from __future__ import annotations
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from markflow import __version__
from markflow.config import (
    AppConfig,
    DEFAULT_CONFIG_PATH,
    LLMConfig,
    CosCredentials,
    load_config,
    save_config,
)
from markflow.pipeline import process_file

app = typer.Typer(
    name="markflow",
    help="将 PDF / DOCX 转换为 Hexo / Hugo Markdown 博客文章",
    add_completion=False,
)
console = Console()


# ------------------------------------------------------------------
# convert (default command)
# ------------------------------------------------------------------

@app.command(name="convert", help="转换一个或多个文件")
def convert(
    files: Annotated[
        Optional[list[Path]],
        typer.Argument(help="要转换的 PDF / DOCX 文件"),
    ] = None,
    dir_path: Annotated[
        Optional[Path],
        typer.Option("--dir", "-d", help="批量转换目录下所有 PDF/DOCX"),
    ] = None,
    config_path: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="指定配置文件路径"),
    ] = None,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="跳过 LLM，仅做格式转换"),
    ] = False,
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="输出路径（仅单文件模式）"),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", "-m", help="临时覆盖 LLM 模型"),
    ] = None,
    preset: Annotated[
        Optional[str],
        typer.Option("--preset", "-p", help="Front Matter 格式：hexo | hugo"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="非交互模式，自动选择第一个标题"),
    ] = False,
) -> None:
    cfg = _load_cfg(config_path)

    # Collect input files
    inputs: list[Path] = []
    if files:
        inputs.extend(files)
    if dir_path:
        if not dir_path.is_dir():
            console.print(f"[red]目录不存在: {dir_path}[/red]")
            raise typer.Exit(1)
        inputs.extend(
            p for p in dir_path.rglob("*")
            if p.suffix.lower() in (".pdf", ".docx")
        )

    if not inputs:
        console.print("[red]未指定任何输入文件。使用 markflow --help 查看帮助。[/red]")
        raise typer.Exit(1)

    if output and len(inputs) > 1:
        console.print("[red]--output 仅支持单文件模式[/red]")
        raise typer.Exit(1)

    console.print(Panel(f"[bold cyan]MarkFlow v{__version__}[/bold cyan]  共 {len(inputs)} 个文件"))

    success, failed = 0, 0
    for path in inputs:
        console.rule(f"[bold]{path.name}[/bold]")
        try:
            process_file(
                path,
                cfg,
                no_llm=no_llm,
                preset=preset,
                model_override=model,
                output_path=output if len(inputs) == 1 else None,
                interactive=not yes,
            )
            success += 1
        except Exception as e:
            console.print(f"[red]✗ 处理失败: {e}[/red]")
            failed += 1

    console.rule()
    console.print(f"完成：[green]{success} 成功[/green]  [red]{failed} 失败[/red]")
    if failed:
        raise typer.Exit(1)


# ------------------------------------------------------------------
# init
# ------------------------------------------------------------------

@app.command(name="init", help="交互式初始化 MarkFlow 配置文件")
def init(
    config_path: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="配置文件保存路径"),
    ] = None,
) -> None:
    target = config_path or DEFAULT_CONFIG_PATH
    console.print(Panel(f"[bold cyan]MarkFlow 配置向导[/bold cyan]\n配置文件: {target}"))

    if target.exists():
        if not Confirm.ask(f"配置文件已存在，是否覆盖？", default=False):
            raise typer.Exit()

    # LLM
    console.print("\n[bold]1. LLM 配置[/bold]")
    provider = Prompt.ask(
        "Provider",
        choices=["openai", "anthropic", "deepseek", "ollama"],
        default="openai",
    )
    api_key = Prompt.ask("API Key（输入后不会显示）", password=True, default="")
    base_url_defaults = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "ollama": "http://localhost:11434/v1",
    }
    base_url = Prompt.ask("Base URL", default=base_url_defaults.get(provider, ""))
    model_defaults = {
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-6",
        "deepseek": "deepseek-chat",
        "ollama": "llama3",
    }
    model = Prompt.ask("模型名", default=model_defaults.get(provider, "gpt-4o"))

    # COS
    console.print("\n[bold]2. 腾讯云 COS（留空则使用 PicGo 配置）[/bold]")
    picgo_path_str = Prompt.ask(
        "PicGo 配置路径",
        default=str(Path.home() / ".picgo" / "config.json"),
    )
    cdn_domain = Prompt.ask("CDN 域名（可选，如 https://img.example.com）", default="")

    # Output
    console.print("\n[bold]3. 输出配置[/bold]")
    output_dir = Prompt.ask("输出目录", default="./output")
    preset = Prompt.ask("博客平台", choices=["hexo", "hugo"], default="hexo")

    cfg = AppConfig(
        picgo_config=Path(picgo_path_str),
        cdn_domain=cdn_domain,
        output_dir=Path(output_dir),
        preset=preset,
        llm=LLMConfig(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
        ),
    )
    save_config(cfg, target)
    console.print(f"\n[green]✓ 配置已保存至 {target}[/green]")


# ------------------------------------------------------------------
# version
# ------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-v", help="显示版本号", is_eager=True),
    ] = False,
) -> None:
    if version:
        console.print(f"MarkFlow v{__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        # No subcommand: treat remaining args as files for convert
        pass


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _load_cfg(config_path: Path | None) -> AppConfig:
    try:
        cfg = load_config(config_path)
    except Exception as e:
        console.print(f"[red]配置加载失败: {e}[/red]")
        raise typer.Exit(1)

    if not DEFAULT_CONFIG_PATH.exists() and not config_path:
        console.print(
            "[yellow]提示：未找到配置文件，运行 [bold]markflow init[/bold] 初始化配置[/yellow]"
        )
    return cfg
