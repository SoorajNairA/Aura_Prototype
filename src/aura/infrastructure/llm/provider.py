from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass,field
from typing import Any, Protocol

@dataclass(frozen=True)
class ModelGenerationResult:
    text:str
    input_tokens:int|None=None
    output_tokens:int|None=None
    total_tokens:int|None=None
    model:str|None=None
    metadata:dict[str,Any]=field(default_factory=dict)


class ModelProvider(Protocol):
    """Provider-neutral model access used by future Planner implementations."""

    def generate(self, messages: list[dict[str, str]], *, system_prompt: str | None = None, max_tokens: int = 512) -> str: ...
    def stream_generate(self, messages: list[dict[str, str]], *, system_prompt: str | None = None, max_tokens: int = 512) -> Iterator[str]: ...
    def is_available(self) -> bool: ...
    def get_diagnostics(self) -> dict[str, Any]: ...


class ConversationModelAdapter:
    """Adapt the proven legacy ConversationModel without importing its backend."""

    def __init__(self, model: Any) -> None:
        self._model = model

    def generate(self, messages: list[dict[str, str]], *, system_prompt: str | None = None, max_tokens: int = 512) -> str:
        return self._model.generate(messages, system_prompt, max_tokens)

    def stream_generate(self, messages: list[dict[str, str]], *, system_prompt: str | None = None, max_tokens: int = 512) -> Iterator[str]:
        return self._model.stream_generate(messages, system_prompt, max_tokens)

    def is_available(self) -> bool:
        return bool(self._model.is_available())

    def get_diagnostics(self) -> dict[str, Any]:
        return dict(self._model.get_diagnostics())
