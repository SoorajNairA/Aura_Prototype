from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.integration
def test_normal_supervisor_construction_does_not_import_unreal() -> None:
    code = r"""
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import aura.legacy.assistant.orchestrator as module
from aura.app.config import Settings

class STT:
    def __init__(self, *args, **kwargs): pass
class TTS:
    def __init__(self, *args, **kwargs): pass
class LLM:
    def __init__(self, *args, **kwargs): pass
    def set_available_tools(self, tools): self.tools = tools

module.AudioIO = lambda **kwargs: object()
module.STTService = STT
module.TTSService = TTS
module.LLMService = LLM

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    settings = replace(Settings(), memory_dir=root / 'memory', log_dir=root / 'logs', auto_warmup=False)
    module.AuraSupervisor(settings)

assert 'aura.legacy.unreal.domain' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=20
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
