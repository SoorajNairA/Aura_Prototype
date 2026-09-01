from __future__ import annotations

import base64
import logging
import os
import queue
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Iterator, Optional

import pyttsx3
import requests
import sounddevice as sd
import numpy as np

from aura.infrastructure.voice.xtts_backend import XTTSBackend
from aura.app.config import aura_data_dir

_logger = logging.getLogger("aura")

# ---------------------------------------------------------------------------
# Streaming chunk accumulation constants
# ---------------------------------------------------------------------------
# Flush a speech chunk when: word_count >= MIN and a natural break is found.
# Force-flush regardless at MAX words.
_MIN_WORDS_PER_CHUNK: int = 8
_MAX_WORDS_PER_CHUNK: int = 18
_SENTENCE_END_CHARS: frozenset = frozenset({"." , "?", "!"})


class TTSService:
    def __init__(
        self,
        elevenlabs_api_key: str,
        voice_id: str,
        model_id: str,
        stability: float,
        similarity_boost: float,
        style: float,
        speaker_boost: bool,
        clarity: float,
        naturalness: float,
        local_rate: int,
        local_voice_index: int,
        backend: str = "pyttsx3",
        voice_reference: str = "",
        device: str = "cuda",
        auto_warmup: bool = True,
        cache_dir: str = str(aura_data_dir() / "models" / "xtts"),
    ) -> None:
        self.elevenlabs_api_key = elevenlabs_api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.stability = stability
        self.similarity_boost = similarity_boost
        self.style = style
        self.speaker_boost = speaker_boost
        self.clarity = clarity
        self.naturalness = naturalness
        self.backend = backend.strip().lower() or "pyttsx3"
        self.local_rate = local_rate
        self.local_voice_index = local_voice_index
        self.local_tts = None
        self.xtts: Optional[XTTSBackend] = None
        self._local_lock = threading.RLock()
        self._backend_lock = threading.RLock()
        self._active_backend = "pyttsx3"
        self._dotnet_tts_available = os.name == "nt"
        self._pyttsx3_available = True
        self._xtts_ready = threading.Event()
        self._xtts_init_done = threading.Event()
        self._xtts_init_thread: Optional[threading.Thread] = None
        self._shutdown_requested = False
        self._amplitude_callback: Optional[Callable[[float], None]] = None

        if self.backend == "elevenlabs" and elevenlabs_api_key:
            _logger.info(f"TTS: ElevenLabs key loaded. Voice='{voice_id}' Model='{model_id}'")

        # Session-level flag: set to False after first 401/403 so subsequent
        # calls skip ElevenLabs entirely, avoiding one wasted HTTP roundtrip
        # per chunk during streaming when the key is exhausted or forbidden.
        self._elevenlabs_available = self.backend == "elevenlabs" and bool(elevenlabs_api_key)

        if self.backend == "xtts":
            try:
                self.xtts = XTTSBackend(
                    device=device,
                    voice_reference=voice_reference or None,
                    cache_dir=cache_dir,
                )
                if auto_warmup:
                    self._initialize_local()
                    self._xtts_init_thread = threading.Thread(
                        target=self._initialize_xtts,
                        args=(True,),
                        daemon=True,
                        name="aura-xtts-initialize",
                    )
                    self._xtts_init_thread.start()
                    _logger.info("XTTS: background initialization and warmup started.")
                else:
                    self._initialize_xtts(warmup=False)
            except Exception as exc:
                _logger.error(f"XTTS: initialization failed; using pyttsx3 fallback: {exc}")
                if self.xtts is not None:
                    self.xtts.shutdown()
                self.xtts = None
                self._initialize_local()
        elif self.backend == "elevenlabs" and self._elevenlabs_available:
            self._active_backend = "elevenlabs"
        else:
            self._initialize_local()

    def speak(self, text: str) -> None:
        if (
            self.backend == "xtts"
            and self.xtts is not None
            and self._active_backend != "xtts"
            and not self._xtts_init_done.is_set()
        ):
            _logger.info(
                "XTTS: speech requested during startup; waiting for cloned voice readiness."
            )
            self._xtts_init_done.wait(timeout=45)

        if self._active_backend == "xtts" and self.xtts is not None:
            try:
                self.xtts.speak(text)
                return
            except Exception as exc:
                _logger.error(f"XTTS: speech failed; switching to pyttsx3 fallback: {exc}")
                try:
                    self.xtts.shutdown()
                except Exception:
                    pass
                self.xtts = None
                self._initialize_local()

        if self._active_backend == "elevenlabs" and self._elevenlabs_available:
            ok = self._speak_elevenlabs(text)
            if ok:
                return
            _logger.warning("TTS: Switching to local pyttsx3 after ElevenLabs failure.")
        else:
            _logger.debug("TTS: ElevenLabs skipped (session-level failure already recorded). Using pyttsx3.")
        self._speak_local(text)

    def shutdown(self) -> None:
        self._shutdown_requested = True
        if (
            self._xtts_init_thread is not None
            and self._xtts_init_thread.is_alive()
            and threading.current_thread() is not self._xtts_init_thread
        ):
            self._xtts_init_thread.join(timeout=2)
        init_still_running = bool(
            self._xtts_init_thread is not None
            and self._xtts_init_thread.is_alive()
        )
        with self._backend_lock:
            if self.xtts is not None and not init_still_running:
                self.xtts.shutdown()
                self.xtts = None
        with self._local_lock:
            if self.local_tts is not None:
                try:
                    self.local_tts.stop()
                except Exception:
                    pass
                self.local_tts = None

    def get_diagnostics(self) -> dict[str, object]:
        if self.xtts is not None:
            diagnostics = self.xtts.get_diagnostics()
            diagnostics["active_backend"] = self._active_backend
            diagnostics["status"] = (
                "ready" if self._xtts_ready.is_set() else "warming"
            )
            return diagnostics
        return {
            "backend": (
                "Windows .NET Speech"
                if self._active_backend == "windows_dotnet"
                else "pyttsx3"
                if self._active_backend == "pyttsx3"
                else "ElevenLabs"
            ),
            "active_backend": self._active_backend,
            "initialized": (
                self.local_tts is not None
                or self._elevenlabs_available
                or self._dotnet_tts_available
            ),
            "pyttsx3_available": self._pyttsx3_available,
            "windows_dotnet_available": self._dotnet_tts_available,
            "device": "cpu",
            "voice": f"local voice {self.local_voice_index}",
            "warmup": False,
            "fallback": "pyttsx3 / Windows .NET Speech",
            "status": "fallback",
        }

    def wait_until_xtts_ready(self, timeout: float | None = None) -> bool:
        return self._xtts_ready.wait(timeout=timeout)

    def wait_until_initialization_done(self, timeout: float | None = None) -> bool:
        return self._xtts_init_done.wait(timeout=timeout)

    def set_amplitude_callback(
        self,
        callback: Optional[Callable[[float], None]],
    ) -> None:
        self._amplitude_callback = callback
        if self.xtts is not None:
            self.xtts.set_amplitude_callback(callback)

    def _initialize_xtts(self, warmup: bool) -> None:
        backend = self.xtts
        if backend is None:
            self._xtts_init_done.set()
            return
        try:
            backend.initialize()
            backend.set_amplitude_callback(self._amplitude_callback)
            if self._shutdown_requested:
                backend.shutdown()
                with self._backend_lock:
                    if self.xtts is backend:
                        self.xtts = None
                return
            if warmup:
                backend.warmup()
            if self._shutdown_requested:
                backend.shutdown()
                with self._backend_lock:
                    if self.xtts is backend:
                        self.xtts = None
                return
            with self._backend_lock:
                self._active_backend = "xtts"
                self._xtts_ready.set()
            diagnostics = backend.get_diagnostics()
            _logger.info(
                "\n"
                + "=" * 49
                + "\nAURA Voice Report\n"
                + "=" * 17
                + f"\nBackend: XTTS-v2"
                + f"\nDevice: {str(diagnostics['device']).upper()}"
                + f"\nGPU: {diagnostics.get('gpu', 'N/A')}"
                + f"\nVoice: {diagnostics['voice']}"
                + f"\nWarmup: {'Complete' if diagnostics['warmup'] else 'Disabled'}"
                + "\nFallback: pyttsx3 / Windows .NET Speech"
                + "\n"
                + "=" * 29
            )
        except Exception as exc:
            _logger.error(f"XTTS: background initialization failed; fallback remains active: {exc}")
            with self._backend_lock:
                if self.xtts is backend:
                    backend.shutdown()
                    self.xtts = None
        finally:
            self._xtts_init_done.set()

    def speak_streamed(self, token_iter: Iterator[str]) -> str:
        """Consume a token stream, accumulate into speech chunks, speak each immediately.

        Architecture:
          - Producer thread: reads tokens, accumulates into word chunks, enqueues each.
          - Consumer (calling thread): dequeues chunks, speaks each via speak().
          - Overlap: while chunk N is playing, chunk N+1 is being assembled.

        Chunking rules:
          - Flush when word_count >= MIN_WORDS and a sentence-end char is found.
          - Force-flush at MAX_WORDS regardless.
          - Flush any remaining buffer when the stream ends.

        Returns the full assembled text (all chunks joined). On streaming failure,
        returns whatever text was assembled before the failure.
        """
        chunk_queue: queue.Queue[str | None] = queue.Queue(maxsize=16)
        errors: list[Exception] = []

        def _producer() -> None:
            buf = ""
            try:
                for token in token_iter:
                    buf += token
                    word_count = len(buf.split())

                    if word_count >= _MIN_WORDS_PER_CHUNK:
                        # Flush at sentence boundary or embedded newline.
                        stripped = buf.rstrip(" \t")
                        last_char = stripped[-1] if stripped else ""
                        has_newline = "\n" in buf[-30:]
                        if last_char in _SENTENCE_END_CHARS or has_newline:
                            chunk_queue.put(buf.strip())
                            buf = ""
                            continue

                    if word_count >= _MAX_WORDS_PER_CHUNK:
                        # Hard cap — flush mid-sentence to stay responsive.
                        chunk_queue.put(buf.strip())
                        buf = ""

            except Exception as exc:
                errors.append(exc)
                _logger.warning(f"TTS stream: producer error — {exc}")
            finally:
                if buf.strip():
                    chunk_queue.put(buf.strip())
                chunk_queue.put(None)  # sentinel

        t_start = time.perf_counter()
        prod = threading.Thread(target=_producer, daemon=True, name="aura-stream-producer")
        prod.start()

        spoken: list[str] = []
        first_chunk_ms: float | None = None

        def chunks() -> Iterator[str]:
            nonlocal first_chunk_ms
            while True:
                try:
                    chunk = chunk_queue.get(timeout=120)
                except queue.Empty:
                    _logger.warning("TTS stream: 120s timeout waiting for chunk. Aborting.")
                    return
                if chunk is None:
                    return
                if first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - t_start) * 1000
                    _logger.info(
                        f"TRACE  Stream first chunk : {first_chunk_ms:.0f}ms  "
                        f"words={len(chunk.split())}"
                    )
                yield chunk

        if self._active_backend == "xtts" and self.xtts is not None:
            try:
                spoken.extend(self.xtts.speak_pipelined(chunks()))
            except Exception as exc:
                errors.append(exc)
                _logger.warning("XTTS streaming pipeline failed: %s", exc)
        else:
            for chunk in chunks():
                spoken.append(chunk)
                self.speak(chunk)

        prod.join(timeout=5)

        if errors:
            _logger.warning(f"TTS stream: {len(errors)} producer error(s). Last: {errors[-1]}")

        full_text = " ".join(spoken)
        total_ms = (time.perf_counter() - t_start) * 1000
        _logger.info(
            f"TRACE  Stream complete    : {total_ms:.0f}ms  "
            f"chunks={len(spoken)}  "
            f"first_chunk={first_chunk_ms:.0f}ms"
            if first_chunk_ms is not None else
            f"TRACE  Stream complete    : {total_ms:.0f}ms  chunks=0  (no output)"
        )
        return full_text

    def _speak_elevenlabs(self, text: str) -> bool:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}?output_format=wav_44100_16"
        headers = {
            "xi-api-key": self.elevenlabs_api_key,
            "accept": "audio/wav",
            "content-type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": max(0.0, min(1.0, self.stability * self.clarity)),
                "similarity_boost": self.similarity_boost,
                "style": max(0.0, min(1.0, self.style * self.naturalness)),
                "use_speaker_boost": self.speaker_boost,
            },
            "pronunciation_dictionary_locators": [],
            "seed": 1,
        }

        try:
            t_http = time.perf_counter()
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            http_ms = (time.perf_counter() - t_http) * 1000
            if not response.ok:
                status = response.status_code
                reason = response.reason or "Unknown"
                _logger.warning(f"TTS: ElevenLabs request failed: {status} {reason}.")
                if status in (401, 403):
                    self._elevenlabs_available = False
                    _logger.warning(
                        f"TTS: ElevenLabs key rejected ({status}). "
                        "Disabling ElevenLabs for this session — all speech will use pyttsx3."
                    )
                return False
            response.raise_for_status()
            _logger.info(f"TRACE  TTS HTTP Request   : {http_ms:.1f}ms  → ElevenLabs {response.status_code} OK")
            with tempfile.NamedTemporaryFile(suffix=".wav", prefix="aura_tts_", delete=False) as f:
                f.write(response.content)
                audio_path = Path(f.name)

            with wave.open(str(audio_path), "rb") as wf:
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                frame_rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())

            dtype = np.int16 if sample_width == 2 else np.int8
            audio = np.frombuffer(frames, dtype=dtype)
            if n_channels > 1:
                audio = audio.reshape(-1, n_channels)
            t_play = time.perf_counter()
            sd.play(audio, frame_rate)
            sd.wait()
            _logger.info(f"TRACE  TTS Audio Playback : {(time.perf_counter() - t_play) * 1000:.1f}ms")
            audio_path.unlink(missing_ok=True)
            return True
        except requests.exceptions.ConnectionError as e:
            _logger.warning(f"TTS: ElevenLabs connection error — {e}.")
            return False
        except requests.exceptions.Timeout:
            _logger.warning("TTS: ElevenLabs request timed out.")
            return False
        except Exception as e:
            _logger.warning(f"TTS: ElevenLabs error — {e}.")
            return False

    def _speak_local(self, text: str) -> None:
        _logger.info("TTS Backend: pyttsx3 (local) speaking.")
        with self._local_lock:
            if self.local_tts is None:
                self._initialize_local()
            if self.local_tts is None:
                if self._speak_windows_dotnet(text):
                    return
                _logger.error("TTS: all local speech fallbacks are unavailable.")
                return
            self.local_tts.say(text)
            self.local_tts.runAndWait()

    def _initialize_local(self) -> bool:
        with self._local_lock:
            if self.local_tts is not None:
                self._active_backend = "pyttsx3"
                return True
            if not self._pyttsx3_available:
                if self._dotnet_tts_available:
                    self._active_backend = "windows_dotnet"
                _logger.debug("TTS: pyttsx3 skipped; backend marked unavailable for this session.")
                return False
            try:
                local_tts = pyttsx3.init()
                local_tts.setProperty("rate", self.local_rate)
                voices = local_tts.getProperty("voices")
                if (
                    isinstance(voices, list)
                    and voices
                    and 0 <= self.local_voice_index < len(voices)
                ):
                    local_tts.setProperty("voice", voices[self.local_voice_index].id)
                self.local_tts = local_tts
                self._active_backend = "pyttsx3"
                _logger.info(
                    f"TTS: pyttsx3 fallback ready. Voice index={self.local_voice_index} "
                    f"rate={self.local_rate}"
                )
                return True
            except Exception as exc:
                self.local_tts = None
                self._pyttsx3_available = False
                _logger.error(f"TTS: pyttsx3 fallback initialization failed: {exc}")
                if self._dotnet_tts_available:
                    self._active_backend = "windows_dotnet"
                    _logger.warning(
                        "TTS: Windows .NET Speech will be used as the final local fallback."
                    )
                return False

    def _speak_windows_dotnet(self, text: str) -> bool:
        if not self._dotnet_tts_available:
            return False
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')); "
            "$s.Speak($t); $s.Dispose()"
        )
        try:
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            self._active_backend = "windows_dotnet"
            _logger.info("TTS Backend: Windows .NET Speech speaking.")
            return True
        except Exception as exc:
            self._dotnet_tts_available = False
            _logger.error(f"TTS: Windows .NET Speech failed: {exc}")
            return False
