"""Draw / pen-lift / fist / erase / idle gesture detection.

Behavioural port of ``fingers_up`` + ``classify_gesture`` from the approved old tracker, with changes:

* OLD: a finger was "up" if tip.y < pip.y in image pixels. That depends on the hand being upright in the
  image and breaks when the hand is rotated or the camera is tilted.
  NEW: a finger is "extended" if its tip is farther from the wrist than its PIP joint by a relative margin
  (tip_dist > pip_dist * EXTENSION_RATIO). Distances use normalized coordinates scaled by the same hand,
  so the rule is invariant to rotation, translation, mirroring and hand size / camera distance.
* OLD: fewer than 21 landmarks -> ``[]`` -> "none" (conflated with "no hand"). NEW: missing landmarks needed
  by a finger make that finger ``None`` and the frame "unknown"; "none" means no tracked hand.
* NEW: a debouncing state machine emits timestamped gesture transitions.

Gesture labels (unchanged from old): fist, pen_lift, draw, erase, idle; plus none, unknown.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .landmark_extractor import (HandObservation, WRIST, INDEX_PIP, INDEX_TIP, MIDDLE_PIP, MIDDLE_TIP,
                                 RING_PIP, RING_TIP, PINKY_PIP, PINKY_TIP)

EXTENSION_RATIO = 1.10   # documented, tunable; tested on constructed poses only (see docs)
FINGERS = (("index", INDEX_PIP, INDEX_TIP), ("middle", MIDDLE_PIP, MIDDLE_TIP),
           ("ring", RING_PIP, RING_TIP), ("pinky", PINKY_PIP, PINKY_TIP))


def _dist(a, b) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def fingers_extended(hand: Optional[HandObservation], ratio: float = EXTENSION_RATIO) -> List[Optional[bool]]:
    """[index, middle, ring, pinky]; ``None`` for a finger whose wrist/PIP/tip landmark is missing."""
    if hand is None:
        return []
    wrist = hand.lm(WRIST)
    out: List[Optional[bool]] = []
    for _, pip_i, tip_i in FINGERS:
        pip, tip = hand.lm(pip_i), hand.lm(tip_i)
        if wrist is None or pip is None or tip is None:
            out.append(None)
            continue
        out.append(_dist(tip, wrist) > _dist(pip, wrist) * ratio)
    return out


def classify_gesture(fingers: List[Optional[bool]]) -> str:
    if not fingers:
        return "none"
    if len(fingers) < 4:
        return "unknown"
    idx, mid, ring, pinky = fingers
    # Index + middle decide draw / pen_lift: if either is unknown the state is unknown (never a guess).
    if idx is None or mid is None:
        return "unknown"
    if ring is None or pinky is None:
        # fist / erase need all four; draw & pen_lift do not need ring/pinky
        if idx and mid:
            return "pen_lift"
        if idx and not mid:
            return "draw"
        return "unknown"
    if not (idx or mid or ring or pinky):
        return "fist"
    if idx and mid:
        return "pen_lift"
    if idx and not mid:
        return "draw"
    if pinky and not idx and not mid:
        return "erase"
    return "idle"


def detect(hand: Optional[HandObservation], ratio: float = EXTENSION_RATIO) -> str:
    return classify_gesture(fingers_extended(hand, ratio))


@dataclass
class GestureEvent:
    timestamp_ms: float
    seq: int
    from_state: str
    to_state: str

    def to_dict(self) -> Dict:
        return {"timestamp_ms": self.timestamp_ms, "seq": self.seq, "from": self.from_state, "to": self.to_state}


class GestureStateMachine:
    """Debounced gesture state. A new raw state must persist ``min_frames`` consecutive frames to take effect.

    The event timestamp is that of the FIRST frame of the new run (the true onset), not the confirmation frame.
    Raw per-frame states are still returned by the caller separately -- debouncing never rewrites raw data.
    """

    def __init__(self, min_frames: int = 2):
        self.min_frames = max(1, min_frames)
        self.state = "none"
        self._cand: Optional[str] = None
        self._cand_n = 0
        self._cand_onset = (0.0, 0)
        self.events: List[GestureEvent] = []

    def update(self, raw_state: str, timestamp_ms: float, seq: int) -> str:
        if raw_state == self.state:
            self._cand, self._cand_n = None, 0
            return self.state
        if raw_state != self._cand:
            self._cand, self._cand_n, self._cand_onset = raw_state, 1, (timestamp_ms, seq)
        else:
            self._cand_n += 1
        if self._cand_n >= self.min_frames:
            self.events.append(GestureEvent(self._cand_onset[0], self._cand_onset[1], self.state, raw_state))
            self.state, self._cand, self._cand_n = raw_state, None, 0
        return self.state
