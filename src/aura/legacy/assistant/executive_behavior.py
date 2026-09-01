from __future__ import annotations

import re
from dataclasses import dataclass


INTERNAL_TERMS = (
    "qwen",
    "ollama",
    "llm",
    "language model",
    "prompt",
    "inference",
    "backend",
    "xtts",
    "pyttsx3",
)


@dataclass(frozen=True)
class ExecutiveStatus:
    label: str
    spoken: str = ""


class ExecutiveBehavior:
    """Small behavior policy for AURA's executive-assistant mode."""

    ANALYZING = ExecutiveStatus("Analyzing request...", "Working on it.")
    PLANNING = ExecutiveStatus("Planning...")
    EXECUTING = ExecutiveStatus("Generating files...")
    VERIFYING = ExecutiveStatus("Verifying results...")
    REVEALING = ExecutiveStatus("Opening result...")
    RECOVERING = ExecutiveStatus("Trying another route.", "I noticed. Trying another approach.")
    COMPLETE = ExecutiveStatus("Completed.")

    @staticmethod
    def sanitize_for_user(text: str) -> str:
        """Remove implementation leakage from spoken/user-facing text."""
        cleaned = text.strip()
        replacements = {
            r"\bOllama\b": "local runtime",
            r"\bQwen(?:[0-9.:-]*\w*)?\b": "local engine",
            r"\bLLM\b": "reasoning engine",
            r"\blanguage model\b": "reasoning engine",
            r"\bprompt\b": "request",
            r"\binference\b": "processing",
            r"\bbackend\b": "system",
            r"\bXTTS(?:-v2)?\b": "voice system",
            r"\bpyttsx3\b": "local voice",
        }
        for pattern, replacement in replacements.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def concise_completion(
        *,
        project_name: str,
        artifact_count: int,
        reveal_method: str = "",
        artifact_label: str = "artifacts",
    ) -> str:
        opened = ""
        if reveal_method:
            opened = " and opened it in VS Code" if reveal_method == "VS Code" else " and opened it"
        noun = artifact_label if artifact_count != 1 else artifact_label.rstrip("s")
        return f"Done. Created {project_name}{opened}. Generated {artifact_count} verified {noun}."

    @staticmethod
    def should_hide_details(text: str) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in INTERNAL_TERMS)
