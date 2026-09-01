from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from aura.infrastructure.voice.tts import TTSService
from aura.infrastructure.voice.xtts_backend import TTSQueue, XTTSBackend


class _FakeXTTSModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def tts_to_file(self, **kwargs) -> None:
        self.calls.append(kwargs)
        sf.write(
            kwargs["file_path"],
            np.zeros(2400, dtype=np.float32),
            24000,
        )


class _FakeLocalEngine:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def setProperty(self, name, value) -> None:
        pass

    def getProperty(self, name):
        return []

    def say(self, text: str) -> None:
        self.spoken.append(text)

    def runAndWait(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _tts_service(**kwargs) -> TTSService:
    defaults = {
        "elevenlabs_api_key": "",
        "voice_id": "",
        "model_id": "",
        "stability": 0.2,
        "similarity_boost": 0.8,
        "style": 0.2,
        "speaker_boost": True,
        "clarity": 0.8,
        "naturalness": 0.8,
        "local_rate": 155,
        "local_voice_index": 0,
    }
    defaults.update(kwargs)
    return TTSService(**defaults)


def test_queue_fifo_and_no_overlap() -> None:
    order: list[int] = []
    active = 0
    max_active = 0
    lock = threading.Lock()

    def consume(value: int) -> None:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        order.append(value)
        with lock:
            active -= 1

    speech_queue = TTSQueue(consume, name="test")
    jobs = [speech_queue.submit(index, wait=False) for index in range(10)]
    for job in jobs:
        job.completed.wait(timeout=2)
        assert job.error is None
    speech_queue.shutdown()

    assert order == list(range(10))
    assert max_active == 1


def test_generation_and_voice_clone() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        reference = root / "voice.wav"
        sf.write(reference, np.zeros(12 * 24000, dtype=np.float32), 24000)

        backend = XTTSBackend(device="cpu")
        fake_model = _FakeXTTSModel()
        backend.model = fake_model
        backend.initialized = True
        backend.device = "cpu"
        backend.clone_voice(reference)

        output = backend.speak_to_file("Hello.", root / "hello.wav")
        assert output.is_file()
        assert fake_model.calls[0]["speaker_wav"] == str(reference.resolve())
        assert fake_model.calls[0]["language"] == "en"
        assert backend.last_generation_ms >= 0
        backend.shutdown()


def test_voice_reference_duration_validation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        reference = Path(temp_dir) / "short.wav"
        sf.write(reference, np.zeros(2 * 24000, dtype=np.float32), 24000)
        backend = XTTSBackend(device="cpu")
        try:
            backend.clone_voice(reference)
        except ValueError as exc:
            assert "10-60 seconds" in str(exc)
        else:
            raise AssertionError("Short voice reference should be rejected.")
        finally:
            backend.shutdown()


def test_missing_xtts_falls_back_to_pyttsx3() -> None:
    fake_local = _FakeLocalEngine()
    with (
        patch("aura.infrastructure.voice.tts.XTTSBackend.initialize", side_effect=RuntimeError("missing model")),
        patch("aura.infrastructure.voice.tts.pyttsx3.init", return_value=fake_local),
    ):
        service = _tts_service(
            backend="xtts",
            voice_reference="missing.wav",
            device="cuda",
            auto_warmup=True,
        )
        service.speak("Fallback works.")
        diagnostics = service.get_diagnostics()
        service.shutdown()

    assert fake_local.spoken == ["Fallback works."]
    assert diagnostics["active_backend"] == "pyttsx3"


def test_broken_pyttsx3_is_skipped_after_first_failure() -> None:
    spoken: list[str] = []

    def dotnet_fallback(service: TTSService, text: str) -> bool:
        spoken.append(text)
        service._active_backend = "windows_dotnet"
        return True

    with (
        patch("aura.infrastructure.voice.tts.pyttsx3.init", side_effect=RuntimeError("COM class not registered")) as init,
        patch.object(TTSService, "_speak_windows_dotnet", dotnet_fallback),
    ):
        service = _tts_service(backend="pyttsx3")
        service.speak("First fallback.")
        service.speak("Second fallback.")
        diagnostics = service.get_diagnostics()
        service.shutdown()

    assert init.call_count == 1
    assert spoken == ["First fallback.", "Second fallback."]
    assert diagnostics["pyttsx3_available"] is False
    assert diagnostics["active_backend"] == "windows_dotnet"


def test_cpu_configuration_is_preserved() -> None:
    backend = XTTSBackend(device="cpu")
    assert backend.requested_device == "cpu"
    backend.shutdown()


def test_speech_waits_for_xtts_warmup() -> None:
    fake_local = _FakeLocalEngine()
    spoken: list[str] = []

    def delayed_initialize(_backend) -> None:
        time.sleep(0.08)

    with (
        patch("aura.infrastructure.voice.tts.XTTSBackend.initialize", delayed_initialize),
        patch("aura.infrastructure.voice.tts.XTTSBackend.warmup", return_value=None),
        patch("aura.infrastructure.voice.tts.XTTSBackend.speak", side_effect=spoken.append),
        patch("aura.infrastructure.voice.tts.XTTSBackend.get_diagnostics", return_value={
            "device": "cpu",
            "voice": "aura_voice",
            "warmup": True,
            "gpu": "CPU",
        }),
        patch("aura.infrastructure.voice.tts.pyttsx3.init", return_value=fake_local),
    ):
        service = _tts_service(
            backend="xtts",
            voice_reference="",
            device="cpu",
            auto_warmup=True,
        )
        service.speak("Use the cloned voice.")
        service.shutdown()

    assert spoken == ["Use the cloned voice."]
    assert fake_local.spoken == []


if __name__ == "__main__":
    tests = [
        test_queue_fifo_and_no_overlap,
        test_generation_and_voice_clone,
        test_voice_reference_duration_validation,
        test_missing_xtts_falls_back_to_pyttsx3,
        test_cpu_configuration_is_preserved,
        test_speech_waits_for_xtts_warmup,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
