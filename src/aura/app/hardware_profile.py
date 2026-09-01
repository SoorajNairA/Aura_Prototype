from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass, replace
from typing import Iterable

import requests

from aura.app.config import Settings


_logger = logging.getLogger("aura")


@dataclass(frozen=True)
class HardwareProfile:
    tier: str
    total_ram_gb: float
    cuda_available: bool
    gpu_name: str
    vram_gb: float
    selected_model: str
    selected_tts: str
    reason: str


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _total_ram_gb() -> float:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0.0
    return round(status.ullTotalPhys / 1024**3, 1)


def _cuda_info() -> tuple[bool, str, float]:
    try:
        import torch

        if not torch.cuda.is_available():
            return False, "None", 0.0
        properties = torch.cuda.get_device_properties(0)
        return (
            True,
            torch.cuda.get_device_name(0),
            round(properties.total_memory / 1024**3, 1),
        )
    except Exception:
        return False, "Unavailable", 0.0


def _installed_ollama_models(base_url: str) -> set[str]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=4)
        response.raise_for_status()
        return {
            str(model.get("name", "")).strip()
            for model in response.json().get("models", [])
            if str(model.get("name", "")).strip()
        }
    except Exception as exc:
        _logger.warning("Hardware profile: Ollama model inventory unavailable: %s", exc)
        return set()


def _model_is_installed(model: str, installed: Iterable[str]) -> bool:
    target = model.removesuffix(":latest")
    return any(name.removesuffix(":latest") == target for name in installed)


def resolve_runtime_settings(
    settings: Settings,
) -> tuple[Settings, HardwareProfile]:
    """Select the local model and TTS backend for the detected hardware."""
    total_ram_gb = _total_ram_gb()
    cuda_available, gpu_name, vram_gb = _cuda_info()

    forced = settings.hardware_profile
    if forced not in {"auto", "performance", "low"}:
        _logger.warning("Unknown AURA_HARDWARE_PROFILE=%r; using auto.", forced)
        forced = "auto"

    capable = (
        total_ram_gb >= settings.performance_min_ram_gb
        and cuda_available
        and vram_gb >= settings.performance_min_vram_gb
    )
    tier = (
        forced
        if forced in {"performance", "low"}
        else "performance"
        if capable
        else "low"
    )

    installed = _installed_ollama_models(settings.ollama_base_url)
    preferred_model = (
        settings.ollama_primary_model
        if tier == "performance"
        else settings.ollama_fallback_model
    )
    explicit_model = settings.ollama_conversation_model
    if explicit_model.lower() != "auto":
        selected_model = explicit_model
        model_reason = "explicit model override"
    elif _model_is_installed(preferred_model, installed) or not installed:
        selected_model = preferred_model
        model_reason = f"{tier} profile"
    elif _model_is_installed(settings.ollama_fallback_model, installed):
        selected_model = settings.ollama_fallback_model
        model_reason = f"{preferred_model} unavailable; installed fallback selected"
    else:
        selected_model = preferred_model
        model_reason = f"{tier} profile; model download required"

    if settings.tts_backend != "auto":
        selected_tts = settings.tts_backend
        tts_reason = "explicit TTS override"
    else:
        xtts_capable = (
            cuda_available
            and vram_gb >= settings.xtts_min_vram_gb
        )
        selected_tts = "xtts" if xtts_capable else "pyttsx3"
        tts_reason = (
            f"CUDA VRAM {vram_gb:.1f} GB"
            if xtts_capable
            else "CUDA/VRAM threshold not met"
        )

    selected_device = "cuda" if selected_tts == "xtts" and cuda_available else "cpu"
    resolved = replace(
        settings,
        ollama_conversation_model=selected_model,
        tts_backend=selected_tts,
        tts_device=selected_device,
        auto_warmup=settings.auto_warmup and selected_tts == "xtts",
    )
    reason = f"Model: {model_reason}; TTS: {tts_reason}"
    profile = HardwareProfile(
        tier=tier,
        total_ram_gb=total_ram_gb,
        cuda_available=cuda_available,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        selected_model=selected_model,
        selected_tts=selected_tts,
        reason=reason,
    )
    return resolved, profile


if __name__ == "__main__":
    resolved_settings, detected_profile = resolve_runtime_settings(Settings())
    if "--model" in sys.argv:
        print(resolved_settings.ollama_conversation_model)
    elif "--tts" in sys.argv:
        print(resolved_settings.tts_backend)
    else:
        print(
            f"{detected_profile.tier}: "
            f"{resolved_settings.ollama_conversation_model} + "
            f"{resolved_settings.tts_backend}"
        )
