"""Text-to-speech output.

Uses flite (fast, offline, robotic -- it suits the character and needs no
network) to render a line to a wav file, then plays it. Playback is serialized
by a lock so overlapping lines don't talk over each other.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading

from .config import VoiceConfig

log = logging.getLogger(__name__)


class Voice:
    def __init__(self, cfg: VoiceConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._available = self._check()

    def _check(self) -> bool:
        from shutil import which

        if which(self.cfg.tts_command) is None:
            log.warning("'%s' not found - speech will be printed only", self.cfg.tts_command)
            return False
        if which(self.cfg.player_command) is None:
            log.warning("'%s' not found - speech will be printed only", self.cfg.player_command)
            return False
        return True

    def set_default_sink(self):
        """Force PulseAudio's default output sink so playback isn't silent.

        PulseAudio sometimes comes up after boot without a usable default sink,
        which makes flite/mpv play into nothing. Run once at startup.
        """
        sink = self.cfg.default_sink
        if not sink:
            return
        try:
            subprocess.run(["pactl", "set-default-sink", sink], check=False)
            log.info("Default audio sink set to %s", sink)
        except FileNotFoundError:
            log.warning("pactl not found - cannot set default sink")
        except Exception as exc:  # noqa: BLE001
            log.warning("could not set default sink: %s", exc)

    def say(self, text: str):
        text = text.strip()
        if not text:
            return
        print(f"Lamuel: {text}")
        if not self._available:
            return

        with self._lock:
            try:
                subprocess.run(
                    [self.cfg.tts_command, f'"{text} "', "-o", self.cfg.temp_wav],
                    check=False,
                )
                if os.path.exists(self.cfg.temp_wav):
                    subprocess.run(
                        [self.cfg.player_command, "--really-quiet", self.cfg.temp_wav],
                        check=False,
                    )
                    os.remove(self.cfg.temp_wav)
            except Exception as exc:  # noqa: BLE001
                log.error("speech failed: %s", exc)

