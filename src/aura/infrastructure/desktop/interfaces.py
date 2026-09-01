from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DesktopActions(Protocol):
    """Optional presentation adapter, never an engineering decision-maker."""

    def open_application(self, application: str) -> bool: ...
    def open_url(self, url: str) -> bool: ...
    def reveal_path(self, path: Path) -> bool: ...
