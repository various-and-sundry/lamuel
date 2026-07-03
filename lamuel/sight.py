"""Vision: face + motion tracking and on-demand snapshots.

Runs the camera in a background thread so the head keeps following a face while
the brain is busy thinking or speaking. Each frame:

  1. Look for faces (Haar cascade). If found, steer toward the largest one.
  2. Otherwise, look for motion (frame differencing) and steer toward the
     largest moving region.

The latest frame is always kept in memory, so a "capture" is just a copy of the
most recent frame -- no ``/tmp/GETIMG`` semaphore or cross-process polling like
the original.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import cv2

from .config import VisionConfig
from .head import HeadController, YAW, PITCH

log = logging.getLogger(__name__)


class VisionTracker:
    def __init__(self, cfg: VisionConfig, head: HeadController, graceful: bool = True, switches=None):
        self.cfg = cfg
        self.head = head
        self.graceful = graceful
        self.switches = switches   # portal on/off flags (tracking)

        self._capture = None
        self._cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._last_gray = None

        # Smoothed target offset (running average), matching the original.
        self._avg_x = 0.0
        self._avg_y = 0.0
        self._frames_since_move = 0

        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._thread = None
        self._running = threading.Event()

    # -- lifecycle ----------------------------------------------------------

    def start(self):
        self._capture = cv2.VideoCapture(self.cfg.camera_index)
        if not self._capture.isOpened():
            msg = f"could not open camera {self.cfg.camera_index}"
            if self.graceful:
                log.warning("%s - vision disabled", msg)
                self._capture = None
                return
            raise RuntimeError(msg)

        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="vision", daemon=True)
        self._thread.start()
        log.info("Vision tracker started on camera %s", self.cfg.camera_index)

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    @property
    def active(self) -> bool:
        return self._capture is not None

    # -- capture for the vision model --------------------------------------

    def snapshot(self) -> str | None:
        """Save the most recent frame to disk and return its path.

        Returns ``None`` if the camera isn't available.
        """
        with self._frame_lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
        if frame is None:
            log.warning("snapshot requested but no frame is available")
            return None

        # Don't let the head drift while we're "taking a picture".
        self.head.hold()
        self._play_shutter()
        cv2.imwrite(self.cfg.snapshot_path, frame)
        log.info("Snapshot saved to %s", self.cfg.snapshot_path)
        return self.cfg.snapshot_path

    def jpeg_frame(self):
        """Return the most recent frame JPEG-encoded, or ``None`` if there is
        no frame yet. Used by the portal's live camera stream."""
        with self._frame_lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else None

    def _play_shutter(self):
        try:
            subprocess.run(
                ["mpv", "--really-quiet", self.cfg.shutter_sound],
                check=False,
            )
        except FileNotFoundError:
            pass  # no player installed; skip the sound effect

    # -- main loop ----------------------------------------------------------

    def _loop(self):
        period = 1.0 / max(1, self.cfg.max_fps)
        while self._running.is_set():
            start = time.monotonic()

            ok, frame = self._capture.read()
            if not ok:
                log.warning("failed to read frame")
                time.sleep(0.05)
                continue

            with self._frame_lock:
                self._latest_frame = frame

            self._process(frame)

            # Throttle so the vision thread leaves CPU for the LLM.
            elapsed = time.monotonic() - start
            if elapsed < period:
                time.sleep(period - elapsed)

    def _process(self, frame):
        height, width = frame.shape[:2]
        scale = width / self.cfg.detection_width
        small = cv2.resize(frame, (self.cfg.detection_width, int(height / scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        target = self._find_face(gray) or self._find_motion(gray, scale)
        self._last_gray = gray

        if target is not None:
            # Detection ran on the downscaled image; map the centre back up.
            cx, cy = target
            self._steer(cx * scale, cy * scale, width, height)

    def _find_face(self, gray):
        faces = self._cascade.detectMultiScale(
            gray, scaleFactor=self.cfg.scale_factor, minNeighbors=self.cfg.min_neighbors
        )
        if len(faces) == 0:
            return None
        # Track the largest face (closest / most prominent person).
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return (x + w // 2, y + h // 2)

    def _find_motion(self, gray, scale):
        if self._last_gray is None or self._last_gray.shape != gray.shape:
            return None
        diff = cv2.absdiff(self._last_gray, gray)
        _, thresh = cv2.threshold(diff, self.cfg.motion_threshold, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        largest = max(contours, key=cv2.contourArea)
        # Compare against the threshold in full-resolution pixels.
        if cv2.contourArea(largest) * scale * scale < self.cfg.min_motion_area:
            return None
        x, y, w, h = cv2.boundingRect(largest)
        return (x + w // 2, y + h // 2)

    def _steer(self, target_x, target_y, width, height):
        """Nudge the head to bring the target toward the centre of the frame.

        Ported from the original tracker: exponential smoothing, a deadband,
        and a re-evaluation interval, with yaw taking priority over pitch.
        """
        # Head tracking can be switched off from the portal. The camera loop
        # (and the live feed) keeps running; we just stop moving the head.
        if self.switches is not None and not self.switches.is_on("tracking"):
            return
        # +offset means the target is left / above centre (see sign convention).
        rel_x = -(target_x - width / 2)
        rel_y = -(target_y - height / 2)

        self._avg_x = (self._avg_x * 4 + rel_x) / 5
        self._avg_y = (self._avg_y * 4 + rel_y) / 5

        self._frames_since_move += 1
        if self._frames_since_move < self.cfg.tracking_interval:
            return

        deadband = self.cfg.deadband_px
        gain = self.cfg.tracking_gain

        if abs(rel_x) > deadband and abs(self._avg_x) > deadband:
            self.head.track(YAW, int(self._avg_x / gain))
            self._frames_since_move = 0
        elif abs(rel_y) > deadband and abs(self._avg_y) > deadband:
            self.head.track(PITCH, int(self._avg_y / gain))
            self._frames_since_move = 0
        else:
            self._frames_since_move = 0

