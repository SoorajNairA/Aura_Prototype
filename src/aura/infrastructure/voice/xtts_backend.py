from __future__ import annotations

import logging
import os
import queue
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Generic, Iterator, TypeVar

from aura.app.config import aura_data_dir

_logger = logging.getLogger("aura")

_T = TypeVar("_T")
_SUPPORTED_REFERENCE_TYPES = {".wav", ".mp3", ".flac"}
_XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


@dataclass
class _QueueJob(Generic[_T]):
    value: _T
    enqueued_at: float = field(default_factory=time.perf_counter)
    completed: threading.Event = field(default_factory=threading.Event)
    result: object | None = None
    error: BaseException | None = None


class TTSQueue(Generic[_T]):
    """Single-consumer FIFO queue used to prevent overlapping speech."""

    def __init__(self, consumer: Callable[[_T], object], name: str = "aura-tts") -> None:
        self._consumer = consumer
        self._queue: queue.Queue[_QueueJob[_T] | None] = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()
        self.last_wait_ms = 0.0
        self._worker = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"{name}-worker",
        )
        self._worker.start()

    @property
    def size(self) -> int:
        return self._queue.qsize()

    def submit(self, value: _T, wait: bool = True) -> object | None:
        with self._lock:
            if self._closed:
                raise RuntimeError("TTS queue is shut down.")
            job = _QueueJob(value=value)
            self._queue.put(job)
            queue_size = self._queue.qsize()
        _logger.info(f"TTS Queue: queued={queue_size}")

        if not wait:
            return job
        job.completed.wait()
        if job.error is not None:
            raise RuntimeError("TTS queue job failed.") from job.error
        return job.result

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(None)
        if wait and threading.current_thread() is not self._worker:
            self._worker.join(timeout=10)

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                try:
                    self.last_wait_ms = (time.perf_counter() - job.enqueued_at) * 1000
                    _logger.info(
                        f"TRACE  TTS Queue Wait     : {self.last_wait_ms:.1f}ms  "
                        f"remaining={self._queue.qsize()}"
                    )
                    job.result = self._consumer(job.value)
                except BaseException as exc:
                    job.error = exc
                finally:
                    job.completed.set()
            finally:
                self._queue.task_done()


class XTTSBackend:
    """Local Coqui XTTS-v2 generation and playback backend.

    Imports are intentionally lazy so AURA can still start and use pyttsx3 when
    XTTS, PyTorch, CUDA, the model, or audio hardware is unavailable.
    """

    def __init__(
        self,
        device: str = "cuda",
        voice_reference: str | Path | None = None,
        language: str = "en",
        use_fp16: bool = True,
        cache_dir: str | Path = aura_data_dir() / "models" / "xtts",
    ) -> None:
        self.requested_device = device.strip().lower() or "cuda"
        self.device = "cpu"
        self.language = language
        self.use_fp16 = use_fp16
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        self._voice_reference_candidate: Path | None = None
        self.voice_reference: Path | None = None
        self._voice_reference_mtime_ns: int | None = None
        self._rejected_reference_mtime_ns: int | None = None
        self.model = None
        self.initialized = False
        self.warmed_up = False
        self.load_time_s = 0.0
        self.last_generation_ms = 0.0
        self.last_playback_ms = 0.0
        self._amplitude_callback: Callable[[float], None] | None = None
        self.fp16_enabled = False
        self._speaker: str | None = None
        self._model_lock = threading.Lock()
        self._speech_lock = threading.Lock()
        self._queue = TTSQueue[str](self._generate_and_play, name="aura-xtts")

        if voice_reference:
            self._voice_reference_candidate = Path(voice_reference).expanduser().resolve()
            if self._voice_reference_candidate.is_file():
                self.clone_voice(self._voice_reference_candidate)
            else:
                _logger.warning(
                    f"XTTS: voice reference not found: {self._voice_reference_candidate}. "
                    "Using the default XTTS speaker and watching for the file."
                )

    @property
    def queue_size(self) -> int:
        return self._queue.size

    @property
    def voice_name(self) -> str:
        if self.voice_reference is not None:
            return self.voice_reference.stem
        return self._speaker or "XTTS default speaker"

    def initialize(self) -> None:
        if self.initialized:
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TTS_HOME", str(self.cache_dir))
        os.environ.setdefault("HF_HOME", str(self.cache_dir / "huggingface"))

        model_dir = (
            self.cache_dir
            / "tts"
            / "tts_models--multilingual--multi-dataset--xtts_v2"
        )
        license_recorded = (model_dir / "tos_agreed.txt").is_file()
        license_from_env = os.environ.get("COQUI_TOS_AGREED") == "1"
        if not license_recorded and not license_from_env:
            raise RuntimeError(
                "XTTS-v2 model license has not been accepted. Review the Coqui CPML "
                "and set COQUI_TOS_AGREED=1 before the first model download."
            )

        started = time.perf_counter()
        try:
            import torch
            from TTS.api import TTS
        except ImportError as exc:
            raise RuntimeError(
                "XTTS dependencies are unavailable. Install the optional XTTS requirements."
            ) from exc

        cuda_available = bool(torch.cuda.is_available())
        if self.requested_device == "cpu":
            self.device = "cpu"
        elif self.requested_device in {"cuda", "auto"} and cuda_available:
            self.device = "cuda"
        else:
            self.device = "cpu"
            if self.requested_device == "cuda":
                _logger.warning("XTTS: CUDA requested but unavailable; using CPU.")

        try:
            model = TTS(model_name=_XTTS_MODEL, progress_bar=False)
            model = model.to(self.device)
            if self.device == "cuda" and self.use_fp16:
                _logger.info(
                    "XTTS: keeping model weights in FP32 because this XTTS build "
                    "does not support blanket FP16 conversion safely."
                )
            speakers = list(getattr(model, "speakers", None) or [])
            self._speaker = speakers[0] if speakers else None
            self.model = model
            self.initialized = True
            self.load_time_s = round(time.perf_counter() - started, 3)
            _logger.info(
                f"XTTS: initialized model='{_XTTS_MODEL}' device={self.device} "
                f"load={self.load_time_s:.3f}s voice='{self.voice_name}'"
            )
        except Exception:
            self.model = None
            self.initialized = False
            if self.device == "cuda":
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
            raise

    def warmup(self) -> None:
        self.initialize()
        warmup_path = self.speak_to_file("Hello.")
        warmup_path.unlink(missing_ok=True)
        self.warmed_up = True
        _logger.info(f"XTTS: warmup complete in {self.last_generation_ms:.1f}ms.")

    def speak(self, text: str) -> None:
        clean_text = " ".join(text.split())
        if not clean_text:
            return
        self.initialize()
        self._queue.submit(clean_text, wait=True)

    def speak_pipelined(self, chunks: Iterator[str]) -> list[str]:
        """Generate the next chunk while the current chunk is playing."""
        generated: queue.Queue[tuple[str, Path] | BaseException | None] = queue.Queue()
        stop_requested = threading.Event()

        def generator() -> None:
            try:
                for chunk in chunks:
                    if stop_requested.is_set():
                        break
                    path = self.speak_to_file(chunk)
                    if stop_requested.is_set():
                        path.unlink(missing_ok=True)
                        break
                    generated.put((chunk, path))
            except BaseException as exc:
                generated.put(exc)
            finally:
                generated.put(None)

        spoken: list[str] = []
        with self._speech_lock:
            worker = threading.Thread(
                target=generator,
                daemon=True,
                name="aura-xtts-pipeline",
            )
            worker.start()
            try:
                while True:
                    item = generated.get()
                    if item is None:
                        break
                    if isinstance(item, BaseException):
                        if spoken:
                            _logger.warning(
                                "XTTS pipeline stopped after %d spoken chunk(s): %s",
                                len(spoken),
                                item,
                            )
                            break
                        raise RuntimeError("XTTS pipeline generation failed.") from item
                    chunk, audio_path = item
                    self._play_audio_file(audio_path)
                    spoken.append(chunk)
            finally:
                stop_requested.set()
                worker.join(timeout=10)
                while not generated.empty():
                    pending = generated.get_nowait()
                    if isinstance(pending, tuple):
                        pending[1].unlink(missing_ok=True)
        return spoken

    def speak_to_file(self, text: str, output_path: str | Path | None = None) -> Path:
        clean_text = " ".join(text.split())
        if not clean_text:
            raise ValueError("XTTS text cannot be empty.")
        self.initialize()
        self._reload_voice_reference_if_changed()

        if output_path is None:
            handle = tempfile.NamedTemporaryFile(
                suffix=".wav",
                prefix="aura_xtts_",
                delete=False,
            )
            handle.close()
            path = Path(handle.name)
        else:
            path = Path(output_path).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)

        kwargs: dict[str, object] = {
            "text": clean_text,
            "language": self.language,
            "file_path": str(path),
        }
        if self.voice_reference is not None:
            kwargs["speaker_wav"] = str(self.voice_reference)
        elif self._speaker is not None:
            kwargs["speaker"] = self._speaker

        started = time.perf_counter()
        try:
            with self._model_lock:
                self.model.tts_to_file(**kwargs)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self.last_generation_ms = (time.perf_counter() - started) * 1000
        _logger.info(
            f"TRACE  XTTS Generation    : {self.last_generation_ms:.1f}ms  "
            f"device={self.device} queue={self.queue_size}"
        )
        return path

    def clone_voice(self, reference_audio: str | Path) -> Path:
        path = Path(reference_audio).expanduser().resolve()
        if path.suffix.lower() not in _SUPPORTED_REFERENCE_TYPES:
            raise ValueError("Voice reference must be WAV, MP3, or FLAC.")
        if not path.is_file():
            raise FileNotFoundError(f"Voice reference not found: {path}")
        try:
            import soundfile as sf

            info = sf.info(str(path))
            duration_s = float(info.duration)
        except Exception as exc:
            raise ValueError(f"Voice reference is unreadable or corrupted: {path}") from exc
        if duration_s < 10.0 or duration_s > 60.0:
            raise ValueError(
                f"Voice reference duration must be 10-60 seconds; got {duration_s:.1f}s."
            )
        self._voice_reference_candidate = path
        self.voice_reference = path
        self._voice_reference_mtime_ns = path.stat().st_mtime_ns
        self._rejected_reference_mtime_ns = None
        _logger.info(
            f"XTTS: voice reference loaded: {path} duration={duration_s:.1f}s"
        )
        return path

    def shutdown(self) -> None:
        self._queue.shutdown(wait=True)
        self.model = None
        self.initialized = False
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def set_amplitude_callback(
        self,
        callback: Callable[[float], None] | None,
    ) -> None:
        self._amplitude_callback = callback

    def get_diagnostics(self) -> dict[str, object]:
        diagnostics: dict[str, object] = {
            "backend": "XTTS-v2",
            "initialized": self.initialized,
            "device": self.device,
            "voice": self.voice_name,
            "warmup": self.warmed_up,
            "fp16": self.fp16_enabled,
            "load_time_s": self.load_time_s,
            "generation_ms": round(self.last_generation_ms, 1),
            "playback_ms": round(self.last_playback_ms, 1),
            "queue_wait_ms": round(self._queue.last_wait_ms, 1),
            "queue_size": self.queue_size,
            "fallback": "pyttsx3 / Windows .NET Speech",
        }
        if self.device == "cuda":
            try:
                import torch

                diagnostics["gpu"] = torch.cuda.get_device_name(0)
                diagnostics["vram_allocated_mb"] = round(
                    torch.cuda.memory_allocated() / 1024**2,
                    1,
                )
                diagnostics["vram_reserved_mb"] = round(
                    torch.cuda.memory_reserved() / 1024**2,
                    1,
                )
            except Exception:
                diagnostics["gpu"] = "CUDA device"
        else:
            diagnostics["gpu"] = "CPU"
        return diagnostics

    def _reload_voice_reference_if_changed(self) -> None:
        path = self._voice_reference_candidate
        if path is None or not path.is_file():
            return
        mtime_ns = path.stat().st_mtime_ns
        if mtime_ns in {
            self._voice_reference_mtime_ns,
            self._rejected_reference_mtime_ns,
        }:
            return
        try:
            self.clone_voice(path)
            _logger.info("XTTS: voice reference change detected and reloaded.")
        except (ValueError, FileNotFoundError) as exc:
            self._rejected_reference_mtime_ns = mtime_ns
            _logger.error(f"XTTS: changed voice reference rejected; keeping current voice: {exc}")

    def _generate_and_play(self, text: str) -> None:
        with self._speech_lock:
            audio_path = self.speak_to_file(text)
            self._play_audio_file(audio_path)

    def _play_audio_file(self, audio_path: Path) -> None:
        import sounddevice as sd
        import soundfile as sf

        try:
            audio, sample_rate = sf.read(str(audio_path), dtype="float32")
            started = time.perf_counter()
            sd.play(audio, sample_rate)
            if self._amplitude_callback is None:
                sd.wait()
            else:
                block_size = max(1, int(sample_rate * 0.04))
                for offset in range(0, len(audio), block_size):
                    block = audio[offset:offset + block_size]
                    rms = float((block.astype("float64") ** 2).mean() ** 0.5)
                    self._amplitude_callback(min(1.0, rms))
                    time.sleep(len(block) / sample_rate)
                sd.wait()
                self._amplitude_callback(0.0)
            self.last_playback_ms = (time.perf_counter() - started) * 1000
            _logger.info(
                f"TRACE  XTTS Playback      : {self.last_playback_ms:.1f}ms  "
                f"queue={self.queue_size}"
            )
        finally:
            audio_path.unlink(missing_ok=True)
