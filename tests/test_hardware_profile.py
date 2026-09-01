from __future__ import annotations

from unittest.mock import patch

from aura.app.config import Settings
from aura.app.hardware_profile import resolve_runtime_settings


def test_performance_profile_uses_qwen8b_and_xtts() -> None:
    settings = Settings(
        ollama_conversation_model="auto",
        tts_backend="auto",
        hardware_profile="auto",
    )
    with (
        patch("aura.app.hardware_profile._total_ram_gb", return_value=16.0),
        patch(
            "aura.app.hardware_profile._cuda_info",
            return_value=(True, "RTX 4060", 8.0),
        ),
        patch(
            "aura.app.hardware_profile._installed_ollama_models",
            return_value={"qwen3:8b", "qwen2.5:3b"},
        ),
    ):
        resolved, profile = resolve_runtime_settings(settings)

    assert profile.tier == "performance"
    assert resolved.ollama_conversation_model == "qwen3:8b"
    assert resolved.tts_backend == "xtts"
    assert resolved.tts_device == "cuda"


def test_four_gb_gpu_uses_qwen3b_with_xtts() -> None:
    settings = Settings(
        ollama_conversation_model="auto",
        tts_backend="auto",
        hardware_profile="auto",
    )
    with (
        patch("aura.app.hardware_profile._total_ram_gb", return_value=16.0),
        patch(
            "aura.app.hardware_profile._cuda_info",
            return_value=(True, "RTX 3050", 4.0),
        ),
        patch(
            "aura.app.hardware_profile._installed_ollama_models",
            return_value={"qwen3:8b", "qwen2.5:3b"},
        ),
    ):
        resolved, profile = resolve_runtime_settings(settings)

    assert profile.tier == "low"
    assert resolved.ollama_conversation_model == "qwen2.5:3b"
    assert resolved.tts_backend == "xtts"
    assert resolved.tts_device == "cuda"


def test_low_profile_uses_qwen3b_and_pyttsx3() -> None:
    settings = Settings(
        ollama_conversation_model="auto",
        tts_backend="auto",
        hardware_profile="auto",
    )
    with (
        patch("aura.app.hardware_profile._total_ram_gb", return_value=8.0),
        patch(
            "aura.app.hardware_profile._cuda_info",
            return_value=(False, "None", 0.0),
        ),
        patch(
            "aura.app.hardware_profile._installed_ollama_models",
            return_value={"qwen2.5:3b"},
        ),
    ):
        resolved, profile = resolve_runtime_settings(settings)

    assert profile.tier == "low"
    assert resolved.ollama_conversation_model == "qwen2.5:3b"
    assert resolved.tts_backend == "pyttsx3"
    assert resolved.tts_device == "cpu"
    assert resolved.auto_warmup is False


def test_missing_8b_uses_installed_3b_fallback() -> None:
    settings = Settings(
        ollama_conversation_model="auto",
        tts_backend="auto",
        hardware_profile="performance",
    )
    with (
        patch("aura.app.hardware_profile._total_ram_gb", return_value=16.0),
        patch(
            "aura.app.hardware_profile._cuda_info",
            return_value=(True, "RTX 3050", 4.0),
        ),
        patch(
            "aura.app.hardware_profile._installed_ollama_models",
            return_value={"qwen2.5:3b"},
        ),
    ):
        resolved, profile = resolve_runtime_settings(settings)

    assert profile.tier == "performance"
    assert resolved.ollama_conversation_model == "qwen2.5:3b"
    assert resolved.tts_backend == "xtts"


if __name__ == "__main__":
    tests = [
        test_performance_profile_uses_qwen8b_and_xtts,
        test_four_gb_gpu_uses_qwen3b_with_xtts,
        test_low_profile_uses_qwen3b_and_pyttsx3,
        test_missing_8b_uses_installed_3b_fallback,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
