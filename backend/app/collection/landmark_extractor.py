"""Hand-landmark data model, parsing and hand selection.

Ported (behaviour only) from the approved old component ``src/hand_tracker.py`` and
rebuilt to satisfy the ParkiScribe raw-data rules:

* all 21 landmarks are kept (normalized x/y/z AND pixel x/y), never reduced to the fingertip;
* missing / invalid landmarks are stored as ``None`` -- never zero-filled;
* every detected hand is its own object (the old code flattened all hands into one list,
  so a second hand silently corrupted landmark indexing);
* the stored coordinate convention is the ORIGINAL (un-mirrored) camera frame, with the
  top-left origin and x to the right. Mirrored-preview input is converted explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence

NUM_LANDMARKS = 21
WRIST = 0
MIDDLE_MCP = 9
INDEX_PIP, INDEX_TIP = 6, 8
MIDDLE_PIP, MIDDLE_TIP = 10, 12
RING_PIP, RING_TIP = 14, 16
PINKY_PIP, PINKY_TIP = 18, 20


@dataclass
class Landmark:
    index: int
    x: float            # normalized, original camera frame
    y: float
    z: float
    px: float           # pixel coordinates in the original camera frame
    py: float
    visibility: Optional[float] = None
    presence: Optional[float] = None


@dataclass
class HandObservation:
    handedness: Optional[str]             # label as seen in the ORIGINAL camera frame
    handedness_score: Optional[float]
    landmarks: List[Optional[Landmark]]   # always length 21; None = missing
    complete: bool = True

    def lm(self, idx: int) -> Optional[Landmark]:
        return self.landmarks[idx] if 0 <= idx < len(self.landmarks) else None

    def n_missing(self) -> int:
        return sum(1 for l in self.landmarks if l is None)


@dataclass
class FrameObservation:
    seq: int
    timestamp_ms: float                   # capture timestamp, NOT synthesized
    width: int
    height: int
    hands: List[HandObservation] = field(default_factory=list)
    status: str = "ok"                    # ok | no_hand | invalid_frame
    timestamp_source: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _valid_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def swap_handedness(label: Optional[str]) -> Optional[str]:
    if label == "Left":
        return "Right"
    if label == "Right":
        return "Left"
    return label


def parse_hand(raw: Dict[str, Any], width: int, height: int, *, mirrored_input: bool = False) -> HandObservation:
    """Parse one raw hand: {"handedness","score","landmarks":[{x,y,z,visibility?,presence?}|None,...]}.

    ``mirrored_input=True`` means the coordinates came from a mirrored selfie preview: x is flipped
    (x -> 1-x) and the handedness label swapped, so stored data are always in the original camera frame.
    """
    lms_in: Sequence[Any] = raw.get("landmarks") or []
    out: List[Optional[Landmark]] = []
    for i in range(NUM_LANDMARKS):
        item = lms_in[i] if i < len(lms_in) else None
        if (not isinstance(item, dict)) or not all(_valid_num(item.get(k)) for k in ("x", "y", "z")):
            out.append(None)          # missing stays missing (never 0,0,0)
            continue
        x = 1.0 - float(item["x"]) if mirrored_input else float(item["x"])
        y, z = float(item["y"]), float(item["z"])
        out.append(Landmark(i, x, y, z, x * width, y * height, item.get("visibility"), item.get("presence")))
    label = raw.get("handedness")
    if mirrored_input:
        label = swap_handedness(label)
    return HandObservation(label, raw.get("score"), out, complete=all(l is not None for l in out))


def parse_frame(raw: Dict[str, Any], *, mirrored_input: bool = False) -> FrameObservation:
    w, h = raw.get("width"), raw.get("height")
    ts = raw.get("timestamp_ms")
    bad = (not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0 or not _valid_num(ts))
    if bad:
        return FrameObservation(int(raw.get("seq", -1)), float(ts) if _valid_num(ts) else float("nan"),
                                w if isinstance(w, int) else 0, h if isinstance(h, int) else 0,
                                [], "invalid_frame", raw.get("timestamp_source", "unknown"))
    hands = [parse_hand(hr, w, h, mirrored_input=mirrored_input) for hr in (raw.get("hands") or [])]
    return FrameObservation(int(raw["seq"]), float(ts), w, h, hands,
                            "ok" if hands else "no_hand", raw.get("timestamp_source", "unknown"))


def hand_size(hand: HandObservation) -> Optional[float]:
    """Wrist -> middle-finger MCP distance (normalized); None if either landmark is missing."""
    a, b = hand.lm(WRIST), hand.lm(MIDDLE_MCP)
    if a is None or b is None:
        return None
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def select_hand(hands: List[HandObservation], strategy: str = "highest_score",
                preferred_handedness: Optional[str] = None) -> Optional[int]:
    """Explicitly choose which detected hand is tracked; returns an index into ``hands`` or None.

    strategies: "highest_score", "largest", "preferred_handedness" (falls back to highest_score).
    Ties break on the lowest index so selection is deterministic.
    """
    if not hands:
        return None
    cand = list(range(len(hands)))
    if strategy == "preferred_handedness" and preferred_handedness:
        pref = [i for i in cand if hands[i].handedness == preferred_handedness]
        if pref:
            cand = pref
    if strategy == "largest":
        return max(cand, key=lambda i: ((hand_size(hands[i]) or -1.0), -i))
    return max(cand, key=lambda i: ((hands[i].handedness_score if hands[i].handedness_score is not None else -1.0), -i))


def extract_from_video(video_path: str, model_path: str, *, mirrored: bool = False,
                       num_hands: int = 2) -> List[FrameObservation]:
    """Offline re-extraction with the MediaPipe Tasks HandLandmarker (VIDEO mode).

    Timestamps are container presentation timestamps (CAP_PROP_POS_MSEC), never index/fps.
    Needs a local ``hand_landmarker.task``. NOT yet validated against recorded video here
    (tracked as pending in PROGRESS.md).
    """
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    opts = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.VIDEO, num_hands=num_hands)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"cannot open video: {video_path}")
    frames: List[FrameObservation] = []
    last_ts = -1
    with vision.HandLandmarker.create_from_options(opts) as landmarker:
        seq = 0
        while True:
            ok, bgr = cap.read()
            ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            if not ok:
                break
            h, w = bgr.shape[:2]
            ts_int = max(int(round(ts_ms)), last_ts + 1)   # MediaPipe needs strictly increasing ints
            last_ts = ts_int
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            res = landmarker.detect_for_video(image, ts_int)
            raw_hands = []
            for hl, hd in zip(res.hand_landmarks, res.handedness):
                raw_hands.append({"handedness": hd[0].category_name, "score": hd[0].score,
                                  "landmarks": [{"x": p.x, "y": p.y, "z": p.z,
                                                 "visibility": getattr(p, "visibility", None),
                                                 "presence": getattr(p, "presence", None)} for p in hl]})
            frames.append(parse_frame({"seq": seq, "timestamp_ms": float(ts_ms), "width": w, "height": h,
                                       "hands": raw_hands, "timestamp_source": "CAP_PROP_POS_MSEC"},
                                      mirrored_input=mirrored))
            seq += 1
    cap.release()
    return frames
