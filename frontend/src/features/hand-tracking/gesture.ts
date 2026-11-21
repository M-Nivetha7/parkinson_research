// TypeScript port of backend/app/collection/gesture_detector.py.
// Fingers are "extended" if tip is farther from the wrist than the PIP joint by a relative margin:
// invariant to rotation, translation, mirroring and hand size (the old rule compared pixel y values).
import { HandObservation, WRIST, INDEX_PIP, INDEX_TIP, MIDDLE_PIP, MIDDLE_TIP, RING_PIP, RING_TIP, PINKY_PIP, PINKY_TIP } from "./landmarks";

export const EXTENSION_RATIO = 1.10;
const FINGERS: [number, number][] = [[INDEX_PIP, INDEX_TIP], [MIDDLE_PIP, MIDDLE_TIP], [RING_PIP, RING_TIP], [PINKY_PIP, PINKY_TIP]];
export type Finger = boolean | null;
export type Gesture = "fist" | "pen_lift" | "draw" | "erase" | "idle" | "none" | "unknown" | "invalid";

export function fingersExtended(hand: HandObservation | null, ratio = EXTENSION_RATIO): Finger[] {
  if (!hand) return [];
  const wrist = hand.landmarks[WRIST];
  return FINGERS.map(([pipI, tipI]) => {
    const pip = hand.landmarks[pipI], tip = hand.landmarks[tipI];
    if (!wrist || !pip || !tip) return null;
    return Math.hypot(tip.x - wrist.x, tip.y - wrist.y) > Math.hypot(pip.x - wrist.x, pip.y - wrist.y) * ratio;
  });
}

export function classifyGesture(f: Finger[]): Gesture {
  if (!f.length) return "none";
  if (f.length < 4) return "unknown";
  const [idx, mid, ring, pinky] = f;
  if (idx === null || mid === null) return "unknown";
  if (ring === null || pinky === null) {
    if (idx && mid) return "pen_lift";
    if (idx && !mid) return "draw";
    return "unknown";
  }
  if (!(idx || mid || ring || pinky)) return "fist";
  if (idx && mid) return "pen_lift";
  if (idx && !mid) return "draw";
  if (pinky && !idx && !mid) return "erase";
  return "idle";
}

export const detect = (hand: HandObservation | null, ratio = EXTENSION_RATIO): Gesture =>
  classifyGesture(fingersExtended(hand, ratio));

export interface GestureEvent { timestamp_ms: number; seq: number; from: string; to: string }

export class GestureStateMachine {
  state: string = "none";
  events: GestureEvent[] = [];
  private cand: string | null = null;
  private candN = 0;
  private onset: [number, number] = [0, 0];
  constructor(public minFrames = 2) { this.minFrames = Math.max(1, minFrames); }

  update(raw: string, timestampMs: number, seq: number): string {
    if (raw === this.state) { this.cand = null; this.candN = 0; return this.state; }
    if (raw !== this.cand) { this.cand = raw; this.candN = 1; this.onset = [timestampMs, seq]; }
    else this.candN += 1;
    if (this.candN >= this.minFrames) {
      this.events.push({ timestamp_ms: this.onset[0], seq: this.onset[1], from: this.state, to: raw });
      this.state = raw; this.cand = null; this.candN = 0;
    }
    return this.state;
  }
}
