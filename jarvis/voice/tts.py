"""Text-to-speech: Piper (best, real British voice) -> espeak-ng -> pyttsx3.

None installed? JARVIS runs in silent chat mode — nothing breaks.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile


class TTS:
    def __init__(self, voice_cfg: dict, root: str):
        self.root = root
        self.backend: str | None = None
        if self._setup_piper(voice_cfg):
            self.backend = "piper"
        elif shutil.which("espeak-ng"):
            self.backend = "espeak-ng"
        else:
            try:
                import pyttsx3
                self._engine = pyttsx3.init()
                try:
                    self._engine.setProperty("voice", self._pick_uk(self._engine))
                    self._engine.setProperty("rate", 165)
                except Exception:
                    pass
                self.backend = "pyttsx3"
            except Exception:
                self.backend = None

    def _setup_piper(self, v: dict) -> bool:
        voice = v.get("piper_voice", "en_GB-alan-medium")
        model_dir = os.path.join(self.root, v.get("piper_model_dir", "data/voices"))
        self._model_path = os.path.join(model_dir, f"{voice}.onnx")
        has_bin = bool(shutil.which("piper") or shutil.which("python") or sys.executable)
        return has_bin and os.path.exists(self._model_path)

    @staticmethod
    def _pick_uk(engine) -> str:
        voices = engine.getProperty("voices")
        for v in voices:
            if "en-GB" in (v.id or "") or "Daniel" in (v.name or ""):
                return v.id
        return voices[0].id

    def _play(self, path: str) -> None:
        sysname = platform.system().lower()
        if sysname == "darwin":
            subprocess.run(["afplay", path], check=False)
        elif sysname == "windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif shutil.which("aplay"):
            subprocess.run(["aplay", "-q", path], check=False)
        else:
            subprocess.run(["ffplay", "-nodisp", "-autoexit", path], check=False)

    def speak(self, text: str) -> None:
        if not self.backend or not text.strip():
            return
        try:
            if self.backend == "piper":
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
                    out = fh.name
                cmd = (["piper"] if shutil.which("piper")
                       else [sys.executable, "-m", "piper"])
                cmd += ["--model", self._model_path, "--output_file", out]
                subprocess.run(cmd, input=text.encode("utf-8"),
                               check=False, timeout=120)
                self._play(out)
                try:
                    os.unlink(out)
                except OSError:
                    pass
            elif self.backend == "espeak-ng":
                subprocess.run(["espeak-ng", "-v", "en-gb", "-s", "165", text],
                               check=False, timeout=60)
            else:
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            pass  # speech must never crash the loop
