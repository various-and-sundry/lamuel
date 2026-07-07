"""Host-level bits the portal exposes: audio volume and resource usage.

Volume goes through ``pactl`` (the same audio stack the rest of Lamuel uses).
Resource figures are read straight from ``/proc`` and sysfs, so there's no
extra dependency -- anything that isn't available on this hardware (for
instance the Jetson GPU-load node on a normal PC) simply comes back as
``None`` and the UI shows a dash.
"""

from __future__ import annotations

import logging
import re
import subprocess

log = logging.getLogger(__name__)

_SINK = "@DEFAULT_SINK@"


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=4)


# -- volume -----------------------------------------------------------------

def _muted() -> bool:
    try:
        r = _run(["pactl", "get-sink-mute", _SINK])
        if r.returncode == 0:
            return "yes" in r.stdout.lower()
        # Older pactl without get-sink-mute: read the sink listing.
        r = _run(["pactl", "list", "sinks"])
        m = re.search(r"Mute:\s*(yes|no)", r.stdout)
        return bool(m and m.group(1) == "yes")
    except Exception:  # noqa: BLE001
        return False


def volume_get() -> dict:
    """Return ``{"volume": 0-100 or None, "muted": bool}`` for the default sink."""
    try:
        r = _run(["pactl", "get-sink-volume", _SINK])
        if r.returncode == 0:
            m = re.search(r"(\d+)%", r.stdout)
            if m:
                return {"volume": int(m.group(1)), "muted": _muted()}
    except FileNotFoundError:
        return {"volume": None, "muted": False}  # pactl not installed
    except Exception as exc:  # noqa: BLE001
        log.debug("volume_get (get-sink-volume) failed: %s", exc)
    # Fallback for older pactl: parse the sink listing.
    try:
        r = _run(["pactl", "list", "sinks"])
        m = re.search(r"Volume:.*?(\d+)%", r.stdout, re.S)
        return {"volume": int(m.group(1)) if m else None, "muted": _muted()}
    except Exception as exc:  # noqa: BLE001
        log.debug("volume_get fallback failed: %s", exc)
        return {"volume": None, "muted": False}


def volume_set(percent) -> dict:
    try:
        percent = max(0, min(100, int(percent)))
        _run(["pactl", "set-sink-volume", _SINK, f"{percent}%"])
    except Exception as exc:  # noqa: BLE001
        log.error("volume_set failed: %s", exc)
    return volume_get()


def volume_mute(muted: bool) -> dict:
    try:
        _run(["pactl", "set-sink-mute", _SINK, "1" if muted else "0"])
    except Exception as exc:  # noqa: BLE001
        log.error("volume_mute failed: %s", exc)
    return volume_get()


# -- resource usage ---------------------------------------------------------

class Resources:
    """CPU / RAM / GPU usage as percentages, read cheaply from the kernel.

    CPU is a delta between calls, so the first reading after construction is
    ``None`` until there's a baseline to compare against.
    """

    # Known Jetson GPU-load sysfs nodes (value is per-mille, 0-1000).
    _GPU_PATHS = (
        "/sys/devices/gpu.0/load",
        "/sys/devices/platform/gpu.0/load",
        "/sys/devices/17000000.gv11b/load",
        "/sys/devices/17000000.ga10b/load",
        "/sys/devices/57000000.gpu/load",
    )

    def __init__(self):
        self._last_cpu = self._read_cpu()

    def _read_cpu(self):
        try:
            with open("/proc/stat") as f:
                vals = list(map(int, f.readline().split()[1:]))
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
            return idle, sum(vals)
        except Exception:  # noqa: BLE001
            return None

    def cpu_percent(self):
        cur = self._read_cpu()
        prev, self._last_cpu = self._last_cpu, cur
        if not cur or not prev:
            return None
        d_total = cur[1] - prev[1]
        d_idle = cur[0] - prev[0]
        if d_total <= 0:
            return None
        return round(100 * (d_total - d_idle) / d_total, 1)

    def ram_percent(self):
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    key, value, *_ = line.replace(":", "").split()
                    info[key] = int(value)  # kB
            total = info.get("MemTotal")
            if not total:
                return None
            avail = info.get("MemAvailable")
            if avail is None:  # older kernels
                avail = info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0)
            return round(100 * (total - avail) / total, 1)
        except Exception:  # noqa: BLE001
            return None

    def gpu_percent(self):
        for path in self._GPU_PATHS:
            try:
                with open(path) as f:
                    return round(int(f.read().strip()) / 10.0, 1)
            except Exception:  # noqa: BLE001
                continue
        return None

    def stats(self) -> dict:
        return {"cpu": self.cpu_percent(),
                "ram": self.ram_percent(),
                "gpu": self.gpu_percent()}
