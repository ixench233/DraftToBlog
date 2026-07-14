from __future__ import annotations
from datetime import datetime, timezone, timedelta

import yaml

from markflow.models import ImageBlock

CST = timezone(timedelta(hours=8))


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
    now = now or datetime.now(tz=CST)
    date_str = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    cover = next((img.cos_url for img in images if img.cos_url), "")

    front_matter: dict = {
        "title": title,
        "date": date_str,
        "lastmod": date_str,
        "tags": tags or [],
        "categories": categories or [],
        "description": description,
    }
    if cover:
        front_matter["cover"] = {"image": cover}

    fm_str = yaml.dump(
        front_matter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    return f"---\n{fm_str}\n---\n\n{rewritten_body.strip()}\n"
