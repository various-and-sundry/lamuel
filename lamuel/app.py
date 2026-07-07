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
from .control import EventBus, Switches
from .head import HeadController
from .hearing import SpeechRecognizer
from .sight import VisionTracker
from .voice import Voice
from .web import WebPortal

log = logging.getLogger(__name__)


class LamuelApp:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        # Shared runtime state the portal and subsystems both touch.
        self.switches = Switches()
        self.bus = EventBus()
        self.head = HeadController(self.cfg.head, graceful=self.cfg.graceful_degradation)
        self.vision = VisionTracker(self.cfg.vision, self.head,
                                    graceful=self.cfg.graceful_degradation, switches=self.switches)
        self.voice = Voice(self.cfg.voice, switches=self.switches, bus=self.bus)
        self.brain = Brain(self.cfg.brain, self.head, self.vision, self.voice)
        self.hearing = SpeechRecognizer(self.cfg.audio, graceful=self.cfg.graceful_degradation,
                                        switches=self.switches, bus=self.bus)
        self.portal = WebPortal(self.cfg.web, vision=self.vision, head=self.head,
                                switches=self.switches, bus=self.bus)

    def _play_startup(self):
        try:
            subprocess.run(["mpv", "--really-quiet", self.cfg.startup_sound], check=False)
        except FileNotFoundError:
            pass

    def run(self):
        # SIGINT/SIGTERM break out of the blocking listen loop; the finally
        # below then tears everything down. systemd sends SIGTERM to stop us.
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        try:
            # Load the language model before anything else. On a cold start this
            # can take a while, so we do it up front: the startup chime and head
            # motion then only happen once Lamuel is actually ready to respond.
            log.info("Loading language model (first start can take a few minutes)...")
            self.brain.warm_up()

            self.voice.set_default_sink()
            self.vision.start()
            self.portal.start()
            # Everything is up (model warm, audio routed, vision tracking): the
            # chime is the last thing before we start listening, so it reliably
            # signals "ready" rather than firing mid-startup.
            self._play_startup()
            log.info("Lamuel online. Speak to begin.")
            self.hearing.listen(self.brain.on_transcript)
        finally:
            self.shutdown()

    def _on_signal(self, *_):
        # Raise into the main thread to unblock listen(); run()'s finally cleans
        # up. listen() catches KeyboardInterrupt, so this is a clean stop.
        raise KeyboardInterrupt

    def shutdown(self):
        if getattr(self, "_shut_down", False):
            return  # idempotent: called from both the signal path and finally
        self._shut_down = True
        log.info("Shutting down...")
        self.vision.stop()
        self.hearing.close()
        self.head.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        LamuelApp().run()
    except KeyboardInterrupt:
        pass  # clean stop (Ctrl-C or SIGTERM) -> exit 0
    except Exception as exc:  # noqa: BLE001
        # A real failure (e.g. no mic on a headless box): exit non-zero so a
        # systemd service with Restart=on-failure will retry.
        logging.getLogger("lamuel.app").error("Lamuel exited with error: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

