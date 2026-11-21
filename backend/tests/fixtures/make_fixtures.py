"""Generate shared landmark fixtures consumed by BOTH the Python and the TypeScript tests.

IMPORTANT: these are CONSTRUCTED fixtures (a geometric hand model), not recordings of a human.
They exist to test logic deterministically. Expected values below are written BY HAND from the
construction, not computed by the code under test. Recorded-video fixtures are still pending
(see PROGRESS.md) and must be added once real/pilot clips exist.

Run:  python backend/tests/fixtures/make_fixtures.py
"""
import json
import math
import os

W, H = 640, 480
OUT = os.path.join(os.path.dirname(__file__), "landmark_fixtures.json")

# local hand frame: wrist at (0,0); "up" is -y; unit ~ image-normalized size at scale 1.0
MCP = {"index": (-0.06, -0.30), "middle": (-0.02, -0.32), "ring": (0.02, -0.31), "pinky": (0.06, -0.27)}
BASE_ID = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}
THUMB = [(-0.08, -0.08), (-0.13, -0.17), (-0.16, -0.24), (-0.18, -0.30)]


def local_hand(extended):
    """extended: set of finger names that are extended. Returns 21 local (x, y) points."""
    pts = [None] * 21
    pts[0] = (0.0, 0.0)
    for i, p in enumerate(THUMB):
        pts[1 + i] = p
    for name, (mx, my) in MCP.items():
        b = BASE_ID[name]
        pts[b] = (mx, my)
        if name in extended:
            pts[b + 1] = (mx, my - 0.18)
            pts[b + 2] = (mx, my - 0.30)
            pts[b + 3] = (mx, my - 0.40)
        else:
            pts[b + 1] = (mx, my - 0.12)
            pts[b + 2] = (mx, my - 0.02)
            pts[b + 3] = (mx, my + 0.08)
    return pts


def place(pts, scale=1.0, rot_deg=0.0, tx=0.5, ty=0.7, mirror=False):
    a = math.radians(rot_deg)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for (x, y) in pts:
        # image aspect: normalized coords are separately scaled; keep isotropic in normalized units for simplicity
        rx, ry = scale * (ca * x - sa * y), scale * (sa * x + ca * y)
        nx, ny = tx + rx, ty + ry
        if mirror:
            nx = 1.0 - nx
        out.append({"x": nx, "y": ny, "z": -0.02, "visibility": 0.99, "presence": 0.99})
    return out


def hand(extended, handedness="Right", score=0.95, **kw):
    return {"handedness": handedness, "score": score, "landmarks": place(local_hand(extended), **kw)}


def frame(seq, t, hands, source="constructed"):
    return {"seq": seq, "timestamp_ms": t, "width": W, "height": H, "hands": hands, "timestamp_source": source}


EXT = {"draw": {"index"}, "pen_lift": {"index", "middle"}, "fist": set(), "erase": {"pinky"},
       "idle": {"ring"}, "open_palm": {"index", "middle", "ring", "pinky"}}
EXPECT_FINGERS = {"draw": [True, False, False, False], "pen_lift": [True, True, False, False],
                  "fist": [False] * 4, "erase": [False, False, False, True],
                  "idle": [False, False, True, False], "open_palm": [True] * 4}
EXPECT_GESTURE = {"draw": "draw", "pen_lift": "pen_lift", "fist": "fist", "erase": "erase",
                  "idle": "idle", "open_palm": "pen_lift"}  # open palm = index+middle up -> pen_lift (old rule)

poses = []
for g in EXT:
    for label, kw in [("upright", {}), ("rot90", {"rot_deg": 90, "tx": 0.4, "ty": 0.5}),
                      ("rot180", {"rot_deg": 180, "tx": 0.5, "ty": 0.3}),
                      ("small", {"scale": 0.5}), ("large", {"scale": 1.4, "ty": 0.9}),
                      ("mirrored", {"mirror": True})]:
        poses.append({"name": f"{g}_{label}", "expected_gesture": EXPECT_GESTURE[g],
                      "expected_fingers": EXPECT_FINGERS[g], "mirrored_input": label == "mirrored",
                      "hand": hand(EXT[g], **kw)})

# missing-landmark poses (None entries, NOT zeros)
miss = hand(EXT["draw"])
miss["landmarks"][8] = None            # index tip missing -> index unknown -> gesture unknown
poses.append({"name": "draw_missing_index_tip", "expected_gesture": "unknown",
              "expected_fingers": [None, False, False, False], "mirrored_input": False, "hand": miss})
miss2 = hand(EXT["draw"])
miss2["landmarks"][20] = None          # pinky tip missing -> draw/pen_lift still decidable
poses.append({"name": "draw_missing_pinky_tip", "expected_gesture": "draw",
              "expected_fingers": [True, False, False, None], "mirrored_input": False, "hand": miss2})
miss3 = hand(EXT["draw"])
miss3["landmarks"][0] = None           # wrist missing -> every finger unknown
poses.append({"name": "draw_missing_wrist", "expected_gesture": "unknown",
              "expected_fingers": [None, None, None, None], "mirrored_input": False, "hand": miss3})
short = hand(EXT["draw"])
short["landmarks"] = short["landmarks"][:15]    # only 15 landmarks delivered
poses.append({"name": "draw_only_15_landmarks", "expected_gesture": "draw",  # draw needs only index+middle
              "expected_fingers": [True, False, None, None], "mirrored_input": False, "hand": short})


def tip_target_hand(state, target, scale=0.5, rot=0.0, **kw):
    """Hand in `state` placed so landmark 8 lands exactly on `target` (x,y)."""
    pts = local_hand(EXT[state])
    a = math.radians(rot)
    tipx, tipy = pts[8]
    rx = scale * (math.cos(a) * tipx - math.sin(a) * tipy)
    ry = scale * (math.sin(a) * tipx + math.cos(a) * tipy)
    return hand(EXT[state], scale=scale, rot_deg=rot, tx=target[0] - rx, ty=target[1] - ry, **kw)


# ---- sequences ----
def path(n, x0, y0, dx, dy):
    return [(x0 + i * dx, y0 + i * dy) for i in range(n)]


def build_two_strokes():
    frames, targets, states = [], [], []
    ts, t = [], 1000.0
    seq = 0

    def add(hands, state, target, dt):
        nonlocal seq, t
        t += dt
        frames.append(frame(seq, round(t, 3), hands))
        targets.append(target)
        states.append(state)
        seq += 1

    # stroke 1: 10 draw frames, one 50.1 ms gap (3 frame periods) before frame 5
    for i, p in enumerate(path(10, 0.30, 0.30, 0.02, 0.01)):
        add([tip_target_hand("draw", p)], "draw", p, 50.1 if i == 5 else 16.7)
    for p in path(4, 0.50, 0.40, 0.01, 0.0):            # pen lift x4
        add([tip_target_hand("pen_lift", p)], "pen_lift", p, 16.7)
    for p in path(10, 0.40, 0.50, -0.02, 0.01):         # stroke 2
        add([tip_target_hand("draw", p)], "draw", p, 16.7)
    for _ in range(3):                                  # hand disappears
        add([], "none", None, 16.7)
    for p in path(5, 0.60, 0.30, 0.0, 0.03):            # stroke 3 after reappearance
        add([tip_target_hand("draw", p)], "draw", p, 16.7)
    return {"name": "three_strokes_with_loss_and_dropped_frames", "frames": frames,
            "tip_targets": targets,
            "expected": {"n_frames": len(frames), "n_strokes": 3, "stroke_sample_counts": [10, 10, 5],
                         "stroke_end_reasons": ["pen_lift", "tracking_loss", "recording_end"],
                         "n_pen_lift_intervals": 2,
                         "n_tracking_loss_events": 1, "tracking_loss_frames": [3],
                         "n_valid_fingertip": len(frames) - 3,
                         "n_dropped_suspected": 2, "median_interval_ms": 16.7,
                         "gesture_event_to_states": ["draw", "pen_lift", "draw", "none", "draw"]}}


def build_time_gap():
    frames, targets, t, seq = [], [], 2000.0, 0
    for i, p in enumerate(path(5, 0.3, 0.3, 0.02, 0.0) + path(5, 0.3, 0.5, 0.02, 0.0)):
        t += 400.0 if i == 5 else 16.7                   # 400 ms gap, still 'draw' state throughout
        frames.append(frame(seq, round(t, 3), [tip_target_hand("draw", p)]))
        targets.append(p)
        seq += 1
    return {"name": "time_gap_splits_stroke", "frames": frames, "tip_targets": targets,
            "expected": {"n_frames": 10, "n_strokes": 2, "stroke_sample_counts": [5, 5],
                         "stroke_end_reasons": ["time_gap", "recording_end"]}}


def build_multi_hand():
    # frame: hand A Left score .9 in DRAW, hand B Right score .6 in PEN_LIFT
    a = tip_target_hand("draw", (0.25, 0.4), handedness="Left", score=0.9)
    b = tip_target_hand("pen_lift", (0.75, 0.4), handedness="Right", score=0.6)
    return {"name": "two_hands", "frames": [frame(0, 100.0, [a, b])],
            "expected": {"highest_score_index": 0, "preferred_right_index": 1, "largest_index": 0,
                         "highest_score_tip_x": 0.25, "preferred_right_tip_x": 0.75}}


fx = {"description": "CONSTRUCTED geometric fixtures, not human recordings. Shared by Python and TypeScript tests.",
      "image": {"width": W, "height": H}, "extension_ratio": 1.10,
      "poses": poses, "sequences": [build_two_strokes(), build_time_gap()], "multi_hand": build_multi_hand()}
with open(OUT, "w") as fh:
    json.dump(fx, fh)
print("wrote", OUT, len(poses), "poses")
