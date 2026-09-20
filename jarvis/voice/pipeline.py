"""Voice loop: wake word -> listen -> transcribe -> think -> speak.

Runs as a daemon thread. Every heavy dependency is imported lazily, so the
UI keeps working in chat mode even when none of the voice stack is installed.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("jarvis.voice")

SAMPLE_RATE = 16000
FRAME = 1280          # samples per callback (openWakeWord frame size)
SILENCE_MS = 700      # trailing silence that ends a command
MAX_SECONDS = 12


class VoicePipeline(threading.Thread):
    def __init__(self, jarvis, voice_cfg: dict, root: str):
        super().__init__(daemon=True, name="jarvis-voice")
        self.jarvis = jarvis
        self.cfg = voice_cfg
        self.root = root
        self._stt = None
        self._tts = None
        self._wake = None
        self._recording = False
        self._frames: list = []
        self._silent_since: float | None = None
        self._record_start = 0.0
        self._last_level_push = 0.0
        self._running = True

    def stop(self) -> None:
        self._running = False

    # ---- lazy components ----
    @property
    def stt(self):
        if self._stt is None:
            from .stt import STT
            self._stt = STT(self.cfg.get("stt_model", "base.en"))
        return self._stt

    def _speak(self, text: str) -> None:
        if self._tts is None:
            from .tts import TTS
            self._tts = TTS(self.cfg, self.root)
        if self._tts.backend:
            self.jarvis.set_state("speaking")
            self._tts.speak(text)

    # ---- main loop ----
    def run(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            log.error("Voice mode needs the voice stack: pip install -r requirements-voice.txt")
            self.jarvis.voice_available = False
            return
        try:
            from .wake import WakeWord
            self._wake = WakeWord()
        except Exception as exc:
            log.warning("Wake word unavailable (%s) — browser push-to-talk still works.", exc)
        from .tts import TTS
        self._tts = TTS(self.cfg, self.root)
        self.jarvis.voice_available = True
        log.info("Voice loop up. Wake word: %s",
                 "hey jarvis" if self._wake else "disabled (push-to-talk only)")
        if self._tts.backend:
            self._speak("Systems online. Say Hey JARVIS when you need me.")
        else:
            log.warning("No TTS backend installed — replies will be text only.")
        try:
            with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=FRAME,
                                   dtype="int16", channels=1,
                                   callback=self._callback):
                while self._running:
                    time.sleep(0.2)
        except Exception as exc:
            log.error("Audio stream error: %s", exc)

    # ---- audio callback ----
    def _callback(self, indata, frames, t, status) -> None:
        if self._recording:
            data = bytes(indata)
            self._frames.append(data)
            rms = self._rms(data)
            self._push_level(rms)
            if rms < 300:  # silence
                self._silent_since = self._silent_since or time.time()
                if len(self._frames) > 6 and \
                        time.time() - self._silent_since > SILENCE_MS / 1000:
                    self._finish_recording()
            else:
                self._silent_since = None
            if time.time() - self._record_start > self.cfg.get("listen_seconds_max", MAX_SECONDS):
                self._finish_recording()
        elif self._wake is not None:
            try:
                if self._wake.predict(bytes(indata)):
                    log.info("Wake word detected")
                    self._start_recording()
            except Exception:
                pass

    def _start_recording(self) -> None:
        self._frames = []
        self._silent_since = None
        self._record_start = time.time()
        self._recording = True
        self.jarvis.set_state("listening")

    def _finish_recording(self) -> None:
        if not self._recording:
            return
        self._recording = False
        audio = b"".join(self._frames)
        self._frames = []
        if len(audio) < FRAME * 2:  # shorter than ~0.16 s — ignore
            self.jarvis.set_state("idle")
            return
        try:
            text = self.transcribe_bytes(audio)
        except Exception as exc:
            log.error("STT failed: %s", exc)
            self.jarvis.set_state("idle")
            return
        if not text:
            self.jarvis.set_state("idle")
            return
        self.jarvis.push_user_text(text)
        self.jarvis.set_state("thinking")
        try:
            result = self.jarvis.handle(text)
            self._speak(result["reply"])
        except Exception as exc:
            log.error("handle() failed: %s", exc)
            self._speak("Sorry, something went wrong on my end.")
        self.jarvis.set_state("idle")

    # ---- shared with the browser mic endpoint ----
    def transcribe_bytes(self, data: bytes) -> str:
        return self.stt.transcribe_bytes(data)

    # ---- helpers ----
    @staticmethod
    def _rms(data: bytes) -> float:
        import numpy as np
        arr = np.frombuffer(data, dtype=np.int16).astype("float32")
        return float((arr ** 2).mean()) ** 0.5 if arr.size else 0.0

    def _push_level(self, rms: float) -> None:
        now = time.time()
        if now - self._last_level_push > 0.08:
            self._last_level_push = now
            self.jarvis.push_level(min(1.0, rms / 3000.0))
