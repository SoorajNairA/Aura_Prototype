from __future__ import annotations

import logging
import time
from pathlib import Path

from faster_whisper import WhisperModel

_logger = logging.getLogger("aura")


def _probe_gpu() -> tuple[bool, int]:
    """Return (cuda_available, cuda_device_count) without requiring torch."""
    try:
        import ctranslate2
        count = ctranslate2.get_cuda_device_count()
        return count > 0, count
    except Exception:
        pass
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=4
        )
        if result.returncode == 0:
            gpus = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            return len(gpus) > 0, len(gpus)
    except Exception:
        pass
    return False, 0


class STTService:
    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        self.model_name = model_name
        self.device_requested = device
        self.compute_type = compute_type
        self._transcription_times: list[float] = []

        cuda_available, cuda_count = _probe_gpu()
        if device == "cuda" and not cuda_available:
            _logger.warning(
                "STT: Device 'cuda' was requested but no CUDA-capable GPU was detected. "
                "Faster-Whisper may fall back to CPU or raise an error."
            )
        elif device == "cpu" and cuda_available:
            _logger.info(
                f"STT: GPU detected ({cuda_count} device(s)) but device='cpu' is configured. "
                "Set AURA_STT_DEVICE=cuda in .env to enable GPU acceleration."
            )
        else:
            gpu_status = f"{cuda_count} CUDA device(s)" if cuda_available else "none detected"
            _logger.info(f"STT: GPU status — {gpu_status}.")

        _logger.info(
            f"STT: Loading Faster-Whisper model='{model_name}' "
            f"device='{device}' compute='{compute_type}'"
        )
        t0 = time.perf_counter()
        try:
            self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
            self.load_time_s = round(time.perf_counter() - t0, 3)
            _logger.info(
                f"STT Backend: Faster-Whisper ({model_name}) ready. "
                f"Load time: {self.load_time_s}s"
            )
        except Exception as e:
            self.load_time_s = round(time.perf_counter() - t0, 3)
            _logger.error(f"STT: Faster-Whisper init failed after {self.load_time_s}s — {e}")
            raise

    @property
    def avg_transcription_ms(self) -> float:
        if not self._transcription_times:
            return 0.0
        return round(sum(self._transcription_times) / len(self._transcription_times) * 1000, 1)

    def get_diagnostics(self) -> dict:
        cuda_available, cuda_count = _probe_gpu()
        return {
            "backend": "Faster-Whisper",
            "model": self.model_name,
            "device_requested": self.device_requested,
            "compute_type": self.compute_type,
            "load_time_s": self.load_time_s,
            "avg_transcription_ms": self.avg_transcription_ms,
            "transcription_samples": len(self._transcription_times),
            "cuda_available": cuda_available,
            "cuda_device_count": cuda_count,
            "openai_stt_supported": False,
            "backend_switching_supported": False,
        }

    def transcribe(self, audio_path: Path) -> str:
        t0 = time.perf_counter()
        try:
            segments, _ = self.model.transcribe(str(audio_path), vad_filter=True, language="en")
            text = " ".join(segment.text.strip() for segment in segments).strip()
            elapsed = time.perf_counter() - t0
            self._transcription_times.append(elapsed)
            _logger.debug(
                f"STT: Transcription took {elapsed * 1000:.1f}ms "
                f"(avg {self.avg_transcription_ms}ms over {len(self._transcription_times)} sample(s))"
            )
            audio_path.unlink(missing_ok=True)
            return text
        except Exception as e:
            elapsed = time.perf_counter() - t0
            _logger.error(f"STT: Transcription failed after {elapsed * 1000:.1f}ms for '{audio_path}' — {e}")
            audio_path.unlink(missing_ok=True)
            return ""
