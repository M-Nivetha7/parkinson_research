# Data collection protocol (template, pilot mode only)

This is a template for NONCLINICAL pilot testing with consenting volunteers. It is not an ethics-approved protocol.
Clinical collection requires an approved protocol: an administrator must activate it in the system with the real
committee name, reference number and approval date. The system cannot verify these; a human attests them.

1. Volunteer reads the information text and gives recording consent (separate, optional video consent is stored
   but video is not captured by any current page).
2. Researcher or volunteer creates a pilot session (`POST /api/sessions`).
3. Volunteer writes each prompted item in the air: default 3 repetitions per character (configurable), then words
   and sentences from the configured lists, or free writing. Breaks and skipped items are allowed.
4. After each item the volunteer confirms or corrects what they wrote (`participant_confirmed_label`).
5. Raw frames (all 21 landmarks, real timestamps) are stored before any processing.
6. Volunteer may withdraw at any time; withdrawal currently blocks new collection but does NOT yet delete stored
   recordings (pending).

Environment guidance (to be validated, not established): even lighting, plain background, camera at chest height
about 60 cm away, hand fully in frame, record the camera's measured frame rate (Camera check in the web demo).
