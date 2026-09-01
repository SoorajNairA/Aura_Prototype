from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class VoiceInteraction(Protocol):
    """Voice is an input/narration adapter and cannot mutate project state."""

    def listen_once(self, level_callback: Callable[[float], None] | None = None) -> str: ...
    def narrate(self, text: str) -> None: ...
    def cancel(self) -> None: ...
    def shutdown(self) -> None: ...


class TranscriptOnlyVoice:
    """Deterministic adapter useful for non-audio clients and tests."""

    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript
        self.narration: list[str] = []

    def listen_once(self, level_callback: Callable[[float], None] | None = None) -> str:
        if level_callback:
            level_callback(0.0)
        return self.transcript

    def narrate(self, text: str) -> None:
        self.narration.append(text)

    def cancel(self) -> None: pass
    def shutdown(self) -> None: pass
