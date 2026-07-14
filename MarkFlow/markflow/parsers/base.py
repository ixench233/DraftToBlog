from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path

from markflow.models import ParsedDocument


class BaseParser(ABC):
    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument: ...

    @classmethod
    def supports(cls, path: Path) -> bool:
        return path.suffix.lower() in cls.EXTENSIONS  # type: ignore[attr-defined]
