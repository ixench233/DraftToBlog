from __future__ import annotations
from datetime import datetime

import yaml

from markflow.models import ContentBlock, BlockType, ImageBlock


def render(
    rewritten_body: str,
    title: str,
    description: str,
    tags: list[str],
    categories: list[str],
    images: list[ImageBlock],
    *,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")

    cover = next((img.cos_url for img in images if img.cos_url), "")

    front_matter: dict = {
        "title": title,
        "date": date_str,
        "updated": date_str,
        "tags": tags or [],
        "categories": categories or [],
        "description": description,
    }
    if cover:
        front_matter["cover"] = cover

    # yaml.dump sorts keys by default; preserve insertion order with sort_keys=False
    fm_str = yaml.dump(
        front_matter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    return f"---\n{fm_str}\n---\n\n{rewritten_body.strip()}\n"
