"""Central configuration for Lamuel.

Everything tunable lives here so the rest of the code stays free of magic
numbers. Values can be overridden with environment variables (see ``_env``)
which is handy on the Jetson where you don't want to edit source to change a
device index.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets"


def _env(name: str, default):
    """Read an env var, coercing to the type of ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


@dataclass
class AudioConfig:
    # Path to the unpacked Vosk model directory.
    model_path: str = _env("LAMUEL_VOSK_MODEL", "vosk-model-small-en-us-0.15")
    # Index of the input device as reported by ``python -m lamuel.tools.devices``.
    device_index: int = _env("LAMUEL_MIC_INDEX", 1)
    chunk_size: int = 8000
    # Transcripts equal to any of these are treated as noise and ignored.
    ignore_phrases: tuple = ("", "huh", "the")


@dataclass
class VoiceConfig:
    # flite = fast, offline, robotic. Fits the character and needs no network.
    tts_command: str = _env("LAMUEL_TTS", "flite")
    player_command: str = _env("LAMUEL_PLAYER", "mpv")
    temp_wav: str = "/tmp/lamuel_tts.wav"
    # PulseAudio doesn't reliably set a default output sink at boot, which
    # leaves flite/mpv playing into nothing. Force it at startup. Set
    # LAMUEL_SINK to another index/name, or "" to skip.
    default_sink: str = _env("LAMUEL_SINK", "0")


@dataclass
class VisionConfig:
    # USB webcam. An int selects /dev/video<N>; a string path also works.
    camera_index: int = _env("LAMUEL_CAMERA", 0)
    # Haar cascade tuning.
    scale_factor: float = 1.1
    min_neighbors: int = 5
    # Motion detection.
    motion_threshold: int = 30       # per-pixel diff to count as "changed"
    min_motion_area: int = 500       # ignore contours smaller than this
    # How often the tracker re-evaluates a servo move (in frames).
    tracking_interval: int = 5
    # Detection runs on a frame downscaled to this width (much less CPU than
    # detecting on a full 720p/1080p frame). Steering is scaled back to full res.
    detection_width: int = 320
    # Cap the processing loop to this many frames per second so the vision
    # thread doesn't peg the CPU and starve the LLM.
    max_fps: int = 10
    # Deadband: don't chase a target within this many pixels of centre.
    deadband_px: int = 40
    # Divisor turning a pixel offset into a servo step (bigger = gentler moves).
    tracking_gain: int = 20
    # Where a snapshot is written for the vision model to read.
    snapshot_path: str = "/tmp/lamuel_image.jpg"
    shutter_sound: str = str(ASSETS_DIR / "camera_sound.mp3")


@dataclass
class HeadConfig:
    serial_port: str = _env("LAMUEL_SERIAL", "/dev/ttyACM0")
    baud_rate: int = _env("LAMUEL_BAUD", 9600)
    # The firmware moves the head by the integer we send: +yaw = left,
    # +pitch = up (matching the original code and the Modelfile).
    #
    # Steps are treated as *relative* increments; we keep a software estimate
    # of the current angle so we can clamp to the mechanical limits below. If
    # your firmware instead expects absolute positions, set relative=False.
    relative: bool = True
    yaw_limit: int = 80              # degrees either side of centre
    pitch_limit: int = 45
    # After the LLM commands a deliberate look, autonomous tracking is
    # suspended for this long so the look is actually visible.
    override_hold_s: float = 2.0


@dataclass
class BrainConfig:
    # The persona model built from Modelfile (`ollama create lamuel -f Modelfile`).
    chat_model: str = _env("LAMUEL_MODEL", "lamuel")
    # Vision model used to describe a captured frame.
    vision_model: str = _env("LAMUEL_VISION_MODEL", "llava-phi3:3.8b")
    describe_prompt: str = "Describe the contents of the image with bullet points."
    # Keep the chat model resident in Ollama between turns (avoids reloading it
    # on every utterance). Also used to pre-warm the model at startup. On a
    # memory-tight board where the chat and vision models can't both fit, set
    # LAMUEL_KEEP_ALIVE lower (e.g. "0" to unload immediately after each reply)
    # so a "look" doesn't have to swap the chat model out.
    keep_alive: str = _env("LAMUEL_KEEP_ALIVE", "30m")
    # Guard against a capture -> describe -> capture -> ... loop.
    max_capture_depth: int = 2


@dataclass
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    head: HeadConfig = field(default_factory=HeadConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)

    # When true, missing hardware (mic/camera/serial) logs a warning and the
    # affected subsystem no-ops instead of crashing, so you can develop and
    # test off-robot.
    graceful_degradation: bool = True
    startup_sound: str = str(ASSETS_DIR / "startup.mp3")

