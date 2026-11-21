import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { parseFrame, parseHand, selectHand, NUM_LANDMARKS } from "../src/features/hand-tracking/landmarks";
import { fingersExtended, detect, classifyGesture, GestureStateMachine } from "../src/features/hand-tracking/gesture";
import { buildRawSamples, segmentStrokes, validateTimestamps } from "../src/features/hand-tracking/trajectory";

// Same fixture file as backend/tests (single source of truth for both implementations).
const here = dirname(fileURLToPath(import.meta.url));
const FX = JSON.parse(readFileSync(join(here, "../../backend/tests/fixtures/landmark_fixtures.json"), "utf8"));
const W = FX.image.width, H = FX.image.height;
const SEQ: Record<string, any> = Object.fromEntries(FX.sequences.map((s: any) => [s.name, s]));
const handOf = (p: any) => parseHand(p.hand, W, H, p.mirrored_input);

describe("landmarks", () => {
  it("keeps all 21 landmarks with normalized and pixel coordinates", () => {
    const h = parseHand(FX.poses[0].hand, W, H);
    expect(h.landmarks.length).toBe(NUM_LANDMARKS);
    expect(h.complete).toBe(true);
    for (const l of h.landmarks) { expect(l!.px).toBeCloseTo(l!.x * W, 9); expect(l!.py).toBeCloseTo(l!.y * H, 9); }
  });
  it("missing landmark stays null, never zero", () => {
    const p = FX.poses.find((q: any) => q.name === "draw_missing_index_tip");
    const h = handOf(p);
    expect(h.landmarks[8]).toBeNull();
    expect(h.complete).toBe(false);
  });
  it("short list padded with null; NaN/Infinity become null", () => {
    const p = FX.poses.find((q: any) => q.name === "draw_only_15_landmarks");
    const h = handOf(p);
    expect(h.landmarks.length).toBe(21);
    expect(h.landmarks.slice(15).every((l) => l === null)).toBe(true);
    const raw = JSON.parse(JSON.stringify(FX.poses[0].hand));
    raw.landmarks[3].x = NaN; raw.landmarks[4].y = Infinity;
    const h2 = parseHand(raw, W, H);
    expect(h2.landmarks[3]).toBeNull(); expect(h2.landmarks[4]).toBeNull();
  });
  it("flags invalid frames and no-hand frames", () => {
    expect(parseFrame({ seq: 0, timestamp_ms: NaN, width: 640, height: 480, hands: [] }).status).toBe("invalid_frame");
    expect(parseFrame({ seq: 0, timestamp_ms: 1, width: 0, height: 480, hands: [] }).status).toBe("invalid_frame");
    expect(parseFrame({ seq: 0, timestamp_ms: 1, width: 640, height: 480, hands: [] }).status).toBe("no_hand");
  });
  it("converts mirrored input to the camera frame and swaps handedness", () => {
    const base = FX.poses[0].hand;
    const mir = JSON.parse(JSON.stringify(base));
    for (const l of mir.landmarks) l.x = 1 - l.x;
    mir.handedness = base.handedness === "Right" ? "Left" : "Right";
    const a = parseHand(base, W, H), b = parseHand(mir, W, H, true);
    expect(b.handedness).toBe(a.handedness);
    a.landmarks.forEach((l, i) => expect(b.landmarks[i]!.x).toBeCloseTo(l!.x, 9));
  });
  it("selects hands explicitly", () => {
    const f = parseFrame(FX.multi_hand.frames[0]);
    const e = FX.multi_hand.expected;
    expect(f.hands.length).toBe(2);
    expect(selectHand(f.hands, "highest_score")).toBe(e.highest_score_index);
    expect(selectHand(f.hands, "largest")).toBe(e.largest_index);
    expect(selectHand(f.hands, "preferred_handedness", "Right")).toBe(e.preferred_right_index);
    expect(selectHand(f.hands, "preferred_handedness", "Middle")).toBe(e.highest_score_index);
    expect(selectHand([], "highest_score")).toBeNull();
  });
});

describe("gestures (shared pose fixtures)", () => {
  for (const pose of FX.poses) {
    it(`pose ${pose.name}`, () => {
      const h = handOf(pose);
      expect(fingersExtended(h)).toEqual(pose.expected_fingers);
      expect(detect(h)).toBe(pose.expected_gesture);
    });
  }
  it("classification rules and no-hand", () => {
    expect(classifyGesture([false, false, false, false])).toBe("fist");
    expect(classifyGesture([true, true, false, false])).toBe("pen_lift");
    expect(classifyGesture([true, false, false, false])).toBe("draw");
    expect(classifyGesture([false, false, false, true])).toBe("erase");
    expect(classifyGesture([false, false, true, false])).toBe("idle");
    expect(classifyGesture([])).toBe("none");
    expect(classifyGesture([null, false, false, false])).toBe("unknown");
    expect(detect(null)).toBe("none");
  });
  it("debounces and stamps onset time", () => {
    const sm = new GestureStateMachine(2);
    ["draw", "pen_lift", "draw", "draw", "draw", "pen_lift", "pen_lift"].forEach((s, i) => sm.update(s, 100 + 10 * i, i));
    expect(sm.events.map((e) => [e.from, e.to, e.seq])).toEqual([["none", "draw", 2], ["draw", "pen_lift", 5]]);
    expect(sm.events[0].timestamp_ms).toBe(120);
  });
});

describe("timestamps", () => {
  it("regular, dropped, duplicate, non-monotonic, too short", () => {
    const reg = Array.from({ length: 100 }, (_, i) => i * 16.7);
    const r = validateTimestamps(reg);
    expect(r.monotonic && r.n_dropped_suspected === 0).toBe(true);
    expect(r.median_fps).toBeCloseTo(1000 / 16.7, 6);
    const base = Array.from({ length: 20 }, (_, i) => i * 16.7);
    const gap = base.slice(0, 10).concat(base.slice(10).map((t) => t + 33.4));
    expect(validateTimestamps(gap).n_dropped_suspected).toBe(2);
    const dup = validateTimestamps([0, 16.7, 16.7, 33.4, 50.1]);
    expect(dup.n_duplicates).toBe(1); expect(dup.usable).toBe(false);
    expect(validateTimestamps([0, 16.7, 10, 33.4]).monotonic).toBe(false);
    expect(validateTimestamps([0, 1]).usable).toBe(false);
  });
});

function run(name: string, debounce = 2) {
  const seq = SEQ[name];
  const frames = seq.frames.map((f: any) => parseFrame(f));
  const built = buildRawSamples(frames, { debounceFrames: debounce });
  return { seq, frames, built, seg: segmentStrokes(built.samples) };
}

describe("strokes, pen lift, tracking loss", () => {
  it("three strokes with loss and dropped frames", () => {
    const { seq, frames, built, seg } = run("three_strokes_with_loss_and_dropped_frames");
    const e = seq.expected;
    expect(seg.strokes.map((s) => s.n_samples)).toEqual(e.stroke_sample_counts);
    expect(seg.strokes.map((s) => s.end_reason)).toEqual(e.stroke_end_reasons);
    expect(seg.pen_lift_intervals.length).toBe(e.n_pen_lift_intervals);
    expect(seg.tracking_loss_events.map((x) => x.n_frames)).toEqual(e.tracking_loss_frames);
    expect(built.samples.filter((s) => s.valid).length).toBe(e.n_valid_fingertip);
    expect(built.gesture_events.map((g) => g.to)).toEqual(e.gesture_event_to_states);
    const tq = validateTimestamps(frames.map((f: any) => f.timestamp_ms));
    expect(tq.n_dropped_suspected).toBe(e.n_dropped_suspected);
    expect(tq.median_interval_ms).toBeCloseTo(e.median_interval_ms, 6);
  });
  it("raw fingertip equals landmark 8 exactly; missing is null", () => {
    const { seq, frames, built } = run("three_strokes_with_loss_and_dropped_frames");
    built.samples.forEach((s, i) => {
      const tgt = seq.tip_targets[i];
      if (tgt === null) { expect(s.valid).toBe(false); expect(s.x).toBeNull(); expect(s.px).toBeNull(); }
      else {
        const tip = frames[i].hands[0].landmarks[8];
        expect(s.x).toBe(tip.x); expect(s.y).toBe(tip.y); expect(s.px).toBe(tip.px);
        expect(s.x).toBeCloseTo(tgt[0], 9); expect(s.y).toBeCloseTo(tgt[1], 9);
      }
      expect(s.timestamp_ms).toBe(frames[i].timestamp_ms);
    });
  });
  it("time gap splits a stroke", () => {
    const { seq, seg } = run("time_gap_splits_stroke");
    expect(seg.strokes.map((s) => s.n_samples)).toEqual(seq.expected.stroke_sample_counts);
    expect(seg.strokes.map((s) => s.end_reason)).toEqual(seq.expected.stroke_end_reasons);
  });
  it("debounce=1 yields the same stroke counts", () => {
    const { seq, seg } = run("three_strokes_with_loss_and_dropped_frames", 1);
    expect(seg.strokes.map((s) => s.n_samples)).toEqual(seq.expected.stroke_sample_counts);
  });
});
