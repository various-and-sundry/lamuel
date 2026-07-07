"""Head servo control.

This is the *single* owner of the serial link to the microcontroller. In the
original code both ``main.py`` and ``new_vision.py`` opened ``/dev/ttyACM0``
independently and both issued servo commands, so autonomous tracking and the
LLM's deliberate looks could interleave bytes and fight over the head. Here all
motion goes through one ``HeadController`` guarded by a lock, and a simple
priority scheme lets an LLM command temporarily override tracking.

Wire protocol (unchanged from the original firmware):
    ``X:<int>\\n\\r``   yaw    (+ = left)
    ``Y:<int>\\n\\r``   pitch  (+ = up)
"""

from __future__ import annotations

import logging
import threading
import time

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover - serial may be absent off-robot
    serial = None

from .config import HeadConfig

log = logging.getLogger(__name__)

YAW = "yaw"
PITCH = "pitch"
_AXIS_LETTER = {YAW: "X", PITCH: "Y"}


class HeadController:
    def __init__(self, cfg: HeadConfig, graceful: bool = True):
        self.cfg = cfg
        self._graceful = graceful
        self._lock = threading.Lock()
        self._serial = None
        self._dry_run_warned = False
        self._override_until = 0.0
        # Software estimate of the current angle, used only for clamping.
        self._position = {YAW: 0, PITCH: 0}
        self._limit = {YAW: cfg.yaw_limit, PITCH: cfg.pitch_limit}

        if serial is None:
            self._warn_or_raise("pyserial is not installed")
            return
        try:
            self._serial = serial.Serial(cfg.serial_port, cfg.baud_rate)
            time.sleep(2)  # let the microcontroller finish resetting
            log.info("Serial link open on %s @ %d", cfg.serial_port, cfg.baud_rate)
        except Exception as exc:  # noqa: BLE001 - hardware can fail many ways
            self._serial = None
            self._warn_or_raise(f"could not open serial port {cfg.serial_port}: {exc}")

    def _warn_or_raise(self, message: str):
        if self._graceful:
            log.warning("%s - head control disabled (dry-run)", message)
        else:
            raise RuntimeError(message)

    # -- public API ---------------------------------------------------------

    def look(self, axis: str, amount: int):
        """A deliberate look, e.g. from the LLM. Takes priority over tracking."""
        self._override_until = time.monotonic() + self.cfg.override_hold_s
        self._move(axis, amount)

    def track(self, axis: str, amount: int):
        """A tracking correction from the vision loop. Yields to active looks."""
        if time.monotonic() < self._override_until:
            return  # an LLM look owns the head right now
        self._move(axis, amount)

    def hold(self):
        """Suspend autonomous tracking for the override window (used while
        capturing an image so the head doesn't drift mid-shot)."""
        self._override_until = time.monotonic() + self.cfg.override_hold_s

    # -- internals ----------------------------------------------------------

    def _move(self, axis: str, amount: int):
        if axis not in _AXIS_LETTER:
            raise ValueError(f"unknown axis {axis!r}")

        amount = self._clamp(axis, int(amount))
        if amount == 0:
            return

        message = f"{_AXIS_LETTER[axis]}:{amount}\n\r"
        with self._lock:
            log.debug("head %s -> %s", axis, message.strip())
            if self._serial is None:
                if not self._dry_run_warned:
                    log.warning("head in dry-run (no serial) - movement commands are being ignored")
                    self._dry_run_warned = True
                return  # dry-run
            try:
                self._serial.write(message.encode())
                self._serial.flushInput()
                self._serial.flushOutput()
            except Exception as exc:  # noqa: BLE001
                log.error("serial write failed: %s", exc)

    def _clamp(self, axis: str, amount: int) -> int:
        """Clamp a *relative* step so the tracked position stays within limits.

        With ``relative=False`` the value is treated as an absolute target and
        simply clamped to the mechanical range.
        """
        limit = self._limit[axis]
        if not self.cfg.relative:
            clamped = max(-limit, min(limit, amount))
            self._position[axis] = clamped  # keep the estimate current
            return clamped

        new_position = self._position[axis] + amount
        clamped = max(-limit, min(limit, new_position))
        actual_step = clamped - self._position[axis]
        self._position[axis] = clamped
        return actual_step

    def close(self):
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                finally:
                    self._serial = None
                    log.info("Serial link closed")
