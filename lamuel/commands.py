"""Parse the LLM's reply into a sequence of actions.

The persona (see Modelfile) emits inline control tokens:

    HEAD-YAW: <int>     turn the head (+ = left)
    HEAD-PITCH: <int>   tilt the head (+ = up)
    CAPTURE...          look through the camera and describe the scene

Everything else is speech. This mirrors the original ``main.py`` parsing:
command tokens are pushed onto their own lines, asterisks are stripped, and
each line is classified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"\b(HEAD-YAW|HEAD-PITCH|CAPTURE)", re.IGNORECASE)


@dataclass
class Say:
    text: str


@dataclass
class Look:
    axis: str      # "yaw" or "pitch"
    amount: int


@dataclass
class Capture:
    pass


def normalize(message: str) -> str:
    """Put each control token on its own line and drop markdown asterisks."""
    return _TOKEN_RE.sub(r"\n\1", message).replace("*", "")


def classify(line: str):
    """Classify a single stripped line into one action (or None if blank)."""
    line = line.strip()
    if not line:
        return None
    upper = line.upper()
    if upper.startswith("HEAD-YAW"):
        amount = _extract_int(line)
        return Look("yaw", amount) if amount is not None else None
    if upper.startswith("HEAD-PITCH"):
        amount = _extract_int(line)
        return Look("pitch", amount) if amount is not None else None
    if upper.startswith("CAPTURE"):
        return Capture()
    return Say(line)


def parse(message: str):
    """Yield Say / Look / Capture actions from a raw assistant message."""
    for raw_line in normalize(message).splitlines():
        action = classify(raw_line)
        if action is not None:
            yield action


def _extract_int(line: str):
    """Pull the integer out of e.g. 'HEAD-YAW: 90' or 'HEAD-YAW 90'."""
    match = re.search(r"-?\d+", line.split(":", 1)[-1])
    return int(match.group()) if match else None
