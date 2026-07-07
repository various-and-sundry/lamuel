"""The conversational brain.

Holds the chat history, calls the Ollama persona model, and dispatches the
parsed actions to the head (deliberate looks), the camera (capture + describe),
and the voice (everything else). The capture pathway feeds the vision model's
description back into the conversation as a sensor observation, exactly as the
original did -- but with a depth guard so it can't loop forever.
"""

from __future__ import annotations

import logging
import time

try:
    import ollama
except ImportError:  # pragma: no cover
    ollama = None

from . import commands
from .config import BrainConfig
from .head import HeadController
from .sight import VisionTracker
from .voice import Voice

log = logging.getLogger(__name__)

_SENSOR_PREAMBLE = (
    "SENSOR OUTPUT: {description}\n"
    "This description came from your own camera, not from the person you are "
    "talking to. If they asked what you see, tell them now."
)


class Brain:
    def __init__(
        self,
        cfg: BrainConfig,
        head: HeadController,
        vision: VisionTracker,
        voice: Voice,
    ):
        self.cfg = cfg
        self.head = head
        self.vision = vision
        self.voice = voice
        self.history: list[dict] = []

    def on_transcript(self, text: str):
        """Entry point for a finalized user utterance."""
        log.info("User said: %s", text)
        self._respond(text, role="user")

    def warm_up(self):
        """Preload the chat model so the first real reply isn't slow."""
        if ollama is None:
            return
        try:
            log.info("Warming up '%s'...", self.cfg.chat_model)
            ollama.chat(
                model=self.cfg.chat_model,
                messages=[{"role": "user", "content": "hi"}],
                keep_alive=self.cfg.keep_alive,
            )
            log.info("Model ready.")
        except Exception as exc:  # noqa: BLE001
            log.warning("model warmup skipped: %s", exc)

    # -- core loop ----------------------------------------------------------

    def _respond(self, content: str, role: str, capture_depth: int = 0):
        self.history.append({"role": role, "content": content})
        reply, hit_capture = self._stream_and_dispatch(capture_depth)
        if reply is None:
            self.voice.say("My language processor is not responding.")
            return
        self.history.append({"role": "assistant", "content": reply})
        if hit_capture:
            self._capture_and_describe(capture_depth)

    def _stream_and_dispatch(self, capture_depth: int):
        """Stream the reply, acting on each line the moment it's complete.

        Returns ``(full_text, hit_capture)``. Speaking a sentence as soon as it
        lands means the first words come out while the rest is still being
        generated -- important because a local model can be slow. Returns
        ``(None, False)`` if generation couldn't run at all.
        """
        if ollama is None:
            log.error("ollama is not installed")
            return None, False

        log.info("Thinking...")
        started = time.monotonic()
        full = ""
        dispatched = 0        # complete lines already handled
        hit_capture = False

        try:
            stream = ollama.chat(
                model=self.cfg.chat_model,
                stream=True,
                messages=self.history,
                keep_alive=self.cfg.keep_alive,
            )
            for chunk in stream:
                full += chunk["message"]["content"]
                lines = commands.normalize(full).split("\n")
                # Every line but the last is finished; the last may still grow.
                while dispatched < len(lines) - 1 and not hit_capture:
                    hit_capture = self._dispatch_line(lines[dispatched])
                    dispatched += 1
                if hit_capture:
                    break
            else:
                # Stream ended normally: flush the final pending line too.
                lines = commands.normalize(full).split("\n")
                while dispatched < len(lines) and not hit_capture:
                    hit_capture = self._dispatch_line(lines[dispatched])
                    dispatched += 1
        except Exception as exc:  # noqa: BLE001
            log.error("ollama chat failed: %s", exc)
            return (full or None), hit_capture

        log.info("Replied in %.1fs", time.monotonic() - started)
        return full, hit_capture

    def _dispatch_line(self, line: str) -> bool:
        """Act on one line. Returns True if it was a CAPTURE request."""
        action = commands.classify(line)
        if isinstance(action, commands.Say):
            self.voice.say(action.text)
        elif isinstance(action, commands.Look):
            self.head.look(action.axis, action.amount)
        elif isinstance(action, commands.Capture):
            return True
        return False

    def _capture_and_describe(self, capture_depth: int):
        if capture_depth >= self.cfg.max_capture_depth:
            log.warning("capture depth limit reached; not looking again")
            return

        path = self.vision.snapshot()
        if path is None:
            self._respond(
                _SENSOR_PREAMBLE.format(description="(camera unavailable)"),
                role="user",
                capture_depth=capture_depth + 1,
            )
            return

        description = self._describe(path)
        log.info("Vision description:\n%s", description)
        self._respond(
            _SENSOR_PREAMBLE.format(description=description),
            role="user",
            capture_depth=capture_depth + 1,
        )

    def _describe(self, image_path: str) -> str:
        if ollama is None:
            return "(vision model unavailable)"
        try:
            result = ollama.generate(
                model=self.cfg.vision_model,
                prompt=self.cfg.describe_prompt,
                images=[image_path],
            )
            return result.get("response", "").strip() or "(no description)"
        except Exception as exc:  # noqa: BLE001
            log.error("vision model failed: %s", exc)
            return "(vision model error)"
