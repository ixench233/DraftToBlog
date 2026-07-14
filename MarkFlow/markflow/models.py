from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    IMAGE = "image"
    TABLE = "table"
    CODE = "code"
    LIST = "list"


@dataclass
class ImageBlock:
    index: int
    data: bytes
    ext: str          # 'png' or 'jpg'
    md5: str
    paragraph_idx: int
    cos_url: str = ""
    alt_text: str = ""


@dataclass
class ContentBlock:
    type: BlockType
    content: str = ""
    level: int = 0        # heading level (1-4)
    language: str = ""    # code block language
    image: ImageBlock | None = None


@dataclass
class ParsedDocument:
    blocks: list[ContentBlock] = field(default_factory=list)
    images: list[ImageBlock] = field(default_factory=list)
    detected_lang: str = "zh"
    title_hint: str = ""  # original document title if available
