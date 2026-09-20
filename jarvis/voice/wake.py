"""Wake word: 'Hey JARVIS' via openWakeWord (local, no cloud)."""
from __future__ import annotations

_WK = "hey_jarvis"


class WakeWord:
    def __init__(self, threshold: float = 0.5):
        from openwakeword import Model
        from openwakeword.utils import download_models
        download_models([_WK])
        self.model = Model(wake_words=[_WK], inference_framework="onnx")
        self.threshold = threshold

    def predict(self, int16_frame: bytes) -> bool:
        import numpy as np
        arr = np.frombuffer(int16_frame, dtype=np.int16)
        score = self.model.predict(arr)
        return bool(max(score.values()) >= self.threshold)
