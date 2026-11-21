# Data dictionary (current)

## Stored per recording (folder `<Group>/<participant code>/<session>/<rec_NNNN>/`)
| File | Content |
|---|---|
| `raw_landmarks.json` | every frame: seq, timestamp_ms, width, height, status, timestamp_source, hands[] -> handedness, score, 21 landmarks (index, x, y, z normalized; px, py pixel; visibility, presence) or `null` for missing |
| `raw_fingertip.csv` | landmark 8 per frame: seq, timestamp_ms, valid, x, y, z, px, py, raw_state, state, handedness, hand_count (empty cell = missing, never 0) |
| `gesture_events.json` | debounced transitions: timestamp_ms (onset), seq, from, to |
| `strokes.json` | strokes (sample indices, start/end, end_reason), pen_lift_intervals, tracking_loss_events (derived; raw untouched) |
| `recording_meta.json` | device, mirrored flag, camera resolution, timestamp quality (median interval, fps, dropped estimate), tracking failure rate, control events, `processing_applied_to_raw: false` |

Coordinate convention: original camera frame (not mirrored), origin top-left, x right, y down.

## Database fields worth knowing
`recordings.intended_label` (prompted), `participant_confirmed_label`, `researcher_verified_label`, `predicted_label`
(never overwritten), `is_synthetic`, `quality_status`. Changes to labels are rows in `label_revisions`.
Participant codes: `PD###`, `HC###`, `PILOT###`. Contact details (`participant_contacts`) are separate and no API reads them.
