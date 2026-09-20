"""Speech-to-text via faster-whisper (fully local, no cloud)."""
from __future__ import annotations

import os
import tempfile


class STT:
    def __init__(self, model_size: str = "base.en"):
        from faster_whisper import WhisperModel
        # CPU + int8 runs fine on any laptop; 'base.en' is a good speed/accuracy pick.
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe_bytes(self, data: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fh:
            fh.write(data)
            path = fh.name
        try:
            segments, _info = self.model.transcribe(path, beam_size=1, vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
