"""Application wiring and lifecycle.

Brings up the head, vision, voice, brain, and hearing subsystems, then hands
control to the speech loop. Vision tracking runs on its own thread the whole
time, so the head keeps following a face while the brain is thinking or
speaking. Deliberate looks from the LLM briefly override tracking.
"""

from __future__ import annotations

import logging
import signal
import subprocess

from .brain import Brain
from .config import Config
from .head import HeadController
from .hearing import SpeechRecognizer
from .sight import VisionTracker
from .voice import Voice

log = logging.getLogger(__name__)


class LamuelApp:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.head = HeadController(self.cfg.head, graceful=self.cfg.graceful_degradation)
        self.vision = VisionTracker(self.cfg.vision, self.head, graceful=self.cfg.graceful_degradation)
        self.voice = Voice(self.cfg.voice)
        self.brain = Brain(self.cfg.brain, self.head, self.vision, self.voice)
        self.hearing = SpeechRecognizer(self.cfg.audio, graceful=self.cfg.graceful_degradation)

    def _play_startup(self):
        try:
            subprocess.run(["mpv", "--really-quiet", self.cfg.startup_sound], check=False)
        except FileNotFoundError:
            pass

    def run(self):
        signal.signal(signal.SIGINT, lambda *_: self.shutdown())
        signal.signal(signal.SIGTERM, lambda *_: self.shutdown())

        # Load the language model before anything else. On a cold start this can
        # take a while, so we do it up front: the startup chime and head motion
        # then only happen once Lamuel is actually ready to respond.
        log.info("Loading language model (first start can take a few minutes)...")
        self.brain.warm_up()

        self.voice.set_default_sink()
        self.vision.start()
        # Everything is up (model warm, audio routed, vision tracking): the
        # chime is the last thing before we start listening, so it reliably
        # signals "ready" rather than firing mid-startup.
        self._play_startup()
        log.info("Lamuel online. Speak to begin.")
        try:
            self.hearing.listen(self.brain.on_transcript)
        finally:
            self.shutdown()

    def shutdown(self):
        log.info("Shutting down...")
        self.vision.stop()
        self.hearing.close()
        self.head.close()
        raise SystemExit(0)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LamuelApp().run()


if __name__ == "__main__":
    main()

