"""Speech recognition via Vosk.

Streams microphone audio through a Vosk recognizer and calls a callback with
each finalized transcript. If the microphone (or PyAudio, or the model) isn't
available and graceful degradation is on, it falls back to reading typed lines
from the terminal so you can exercise the whole pipeline off-robot.
"""

from __future__ import annotations

import json
import logging

try:
    import pyaudio
    import vosk
except ImportError:  # pragma: no cover - absent off-robot
    pyaudio = None
    vosk = None

from .config import AudioConfig

log = logging.getLogger(__name__)


class SpeechRecognizer:
    def __init__(self, cfg: AudioConfig, graceful: bool = True):
        self.cfg = cfg
        self.graceful = graceful
        self._pyaudio = None
        self._stream = None
        self._rec = None
        self._available = self._setup()

    def _setup(self) -> bool:
        if pyaudio is None or vosk is None:
            return self._fail("pyaudio/vosk not installed")
        try:
            model = vosk.Model(self.cfg.model_path)
            self._pyaudio = pyaudio.PyAudio()
            info = self._pyaudio.get_device_info_by_index(self.cfg.device_index)
            samplerate = int(info["defaultSampleRate"])
            self._stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=samplerate,
                input=True,
                input_device_index=self.cfg.device_index,
                frames_per_buffer=self.cfg.chunk_size,
            )
            self._stream.start_stream()
            self._rec = vosk.KaldiRecognizer(model, samplerate)
            log.info("Microphone ready (device %d @ %d Hz)", self.cfg.device_index, samplerate)
            return True
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"microphone unavailable: {exc}")

    def _fail(self, message: str) -> bool:
        if self.graceful:
            log.warning("%s - falling back to typed input", message)
            return False
        raise RuntimeError(message)

    def listen(self, on_transcript):
        """Block, delivering each finalized transcript to ``on_transcript``."""
        if not self._available:
            return self._listen_typed(on_transcript)
        return self._listen_audio(on_transcript)

    def _listen_audio(self, on_transcript):
        log.info("Listening...")
        try:
            while True:
                data = self._stream.read(self.cfg.chunk_size, exception_on_overflow=False)
                if self._rec.AcceptWaveform(data):
                    text = json.loads(self._rec.Result()).get("text", "").strip()
                    if text and text not in self.cfg.ignore_phrases:
                        on_transcript(text)
        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            self.close()

    def _listen_typed(self, on_transcript):
        print("[typed-input mode] Type what you'd say to Lamuel (Ctrl-D to quit).")
        try:
            while True:
                try:
                    text = input("you> ").strip()
                except EOFError:
                    break
                if text and text not in self.cfg.ignore_phrases:
                    on_transcript(text)
        except KeyboardInterrupt:
            log.info("Stopped by user")

    def close(self):
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pyaudio is not None:
            self._pyaudio.terminate()
            self._pyaudio = None
        log.info("Audio stream stopped")
