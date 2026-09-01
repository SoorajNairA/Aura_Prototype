from __future__ import annotations

import tempfile
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf


class AudioIO:
    def __init__(
        self,
        sample_rate: int = 16000,
        max_record_seconds: int = 12,
        silence_threshold: float = 0.01,
        silence_hold_seconds: float = 1.2,
    ) -> None:
        self.sample_rate = sample_rate
        self.max_record_seconds = max_record_seconds
        self.silence_threshold = silence_threshold
        self.silence_hold_seconds = silence_hold_seconds

    def record_until_silence(self, level_callback: Optional[Callable[[float], None]] = None) -> Path:
        chunk = 1024
        max_frames = int(self.max_record_seconds * self.sample_rate)
        silence_chunks_needed = int((self.silence_hold_seconds * self.sample_rate) / chunk)

        frames: list[np.ndarray] = []
        total_samples = 0
        silence_chunks = 0

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
            start_time = time.time()
            while total_samples < max_frames:
                data, _ = stream.read(chunk)
                mono = data[:, 0]
                frames.append(mono.copy())
                total_samples += len(mono)

                rms = float(np.sqrt(np.mean(np.square(mono))))
                if level_callback is not None:
                    level_callback(rms)
                if rms < self.silence_threshold:
                    silence_chunks += 1
                else:
                    silence_chunks = 0

                if silence_chunks >= silence_chunks_needed and (time.time() - start_time) > 1.0:
                    break

        all_audio = np.concatenate(frames) if frames else np.zeros((1,), dtype=np.float32)

        with tempfile.NamedTemporaryFile(prefix="aura_input_", suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)

        sf.write(str(path), all_audio, self.sample_rate)
        return path

    def play_wav_bytes(self, wav_bytes: bytes) -> None:
        with tempfile.NamedTemporaryFile(prefix="aura_tts_", suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes)
            wav_path = Path(tmp.name)

        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frame_rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        dtype = np.int16 if sample_width == 2 else np.int8
        audio = np.frombuffer(frames, dtype=dtype)
        if n_channels > 1:
            audio = audio.reshape(-1, n_channels)
        sd.play(audio, frame_rate)
        sd.wait()
        wav_path.unlink(missing_ok=True)
