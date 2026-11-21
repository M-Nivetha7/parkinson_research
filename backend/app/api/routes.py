import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..collection.realtime_recorder import RecordingSession as CaptureSession
from ..core.config import get_settings
from ..database.models import (AuditLog, ClinicalMetadata, Consent, GROUPS, LabelRevision, Participant, Protocol,
                               Recording, RecordingSession, User, utcnow)
from ..database.session import get_db
from ..security.auth import create_token, current_user, hash_password, require_roles, verify_password

router = APIRouter(prefix="/api")
STAFF = ("researcher", "research_admin", "system_admin")
CLINICAL_GROUPS = ("parkinson", "healthy_control")
PREFIX = {"parkinson": "PD", "healthy_control": "HC", "pilot_nonclinical": "PILOT"}
TASKS = ("character", "word", "sentence", "freeform")


def audit(db: Session, user: Optional[User], action: str, target: str | None = None, detail: Dict | None = None):
    db.add(AuditLog(user_id=user.id if user else None, action=action, target=target, detail=detail))


def active_protocol(db: Session) -> Optional[Protocol]:
    return db.scalars(select(Protocol).where(Protocol.status == "active").order_by(Protocol.id.desc())).first()


def next_code(db: Session, group: str) -> str:
    n = db.scalar(select(func.count()).select_from(Participant).where(Participant.group == group)) or 0
    return f"{PREFIX[group]}{n + 1:03d}"


def own_participant(user: User, db: Session) -> Participant:
    if user.participant_id is None:
        raise HTTPException(403, "This account is not linked to a participant")
    return db.get(Participant, user.participant_id)


def can_access(user: User, p: Participant) -> bool:
    return user.role in STAFF or user.participant_id == p.id


# ---------------- auth ----------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Self-registration creates a PILOT (nonclinical) participant account only. Staff/clinical accounts are
    created by an administrator -- self-registration can never grant a role or a clinical group."""
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "Email already registered")
    p = Participant(code=next_code(db, "pilot_nonclinical"), group="pilot_nonclinical")
    db.add(p); db.flush()
    u = User(email=body.email.lower(), password_hash=hash_password(body.password), role="participant", participant_id=p.id)
    db.add(u); db.flush()
    audit(db, u, "auth.register", p.code)
    db.commit()
    return {"user_id": u.id, "participant_code": p.code, "role": u.role}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if u is None or not u.is_active or not verify_password(body.password, u.password_hash):
        audit(db, None, "auth.login_failed", body.email.lower()); db.commit()
        raise HTTPException(401, "Invalid credentials")
    audit(db, u, "auth.login"); db.commit()
    return {"access_token": create_token(u), "token_type": "bearer", "role": u.role}


@router.post("/auth/logout")
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Stateless JWT: the client discards the token. Server-side revocation is NOT implemented (see PROGRESS.md).
    audit(db, user, "auth.logout"); db.commit()
    return {"ok": True, "note": "token discarded client-side; server-side revocation not implemented"}


@router.get("/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Participant, user.participant_id) if user.participant_id else None
    return {"id": user.id, "email": user.email, "role": user.role, "participant_code": p.code if p else None}


# ---------------- protocol ----------------
@router.get("/protocol/status")
def protocol_status(db: Session = Depends(get_db)):
    p = active_protocol(db)
    return {"protocol_active": p is not None, "protocol_version": p.version if p else None,
            "clinical_collection_enabled": p is not None, "pilot_mode_available": True,
            "pilot_mode_label": "Nonclinical testing only - not clinical validation"}


class ActivateIn(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    ethics_committee: str = Field(min_length=3, max_length=255)
    ethics_reference: str = Field(min_length=3, max_length=128)
    approval_date: str = Field(min_length=8, max_length=32)
    consent_version: str = Field(min_length=1, max_length=64)
    repetitions_per_character: int = Field(default=3, ge=1, le=20)

    @field_validator("ethics_committee", "ethics_reference", "approval_date", "version", "consent_version")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


@router.post("/admin/protocol/activate", status_code=201)
def activate_protocol(body: ActivateIn, user: User = Depends(require_roles("research_admin")),
                      db: Session = Depends(get_db)):
    """Only a research administrator can activate a protocol, and only by supplying real ethics details.
    The values are recorded as entered; the system cannot verify them against the committee (a human attests)."""
    for old in db.scalars(select(Protocol).where(Protocol.status == "active")):
        old.status = "retired"
    pr = Protocol(version=body.version, status="active", ethics_committee=body.ethics_committee,
                  ethics_reference=body.ethics_reference, approval_date=body.approval_date,
                  consent_version=body.consent_version, repetitions_per_character=body.repetitions_per_character,
                  activated_by=user.id, activated_at=utcnow())
    db.add(pr); db.flush()
    audit(db, user, "protocol.activate", body.version, {"ethics_reference": body.ethics_reference})
    db.commit()
    return {"protocol_id": pr.id, "status": pr.status}


@router.get("/admin/audit-log")
def audit_log(limit: int = 100, user: User = Depends(require_roles("research_admin", "system_admin")),
              db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))).all()
    return [{"id": r.id, "at": r.at.isoformat(), "user_id": r.user_id, "action": r.action, "target": r.target} for r in rows]


# ---------------- participants ----------------
class ParticipantIn(BaseModel):
    group: str
    age_range: Optional[str] = Field(default=None, max_length=16)
    handedness: Optional[str] = Field(default=None, max_length=16)
    writing_hand: Optional[str] = Field(default=None, max_length=16)
    study_site: Optional[str] = Field(default=None, max_length=128)

    @field_validator("group")
    @classmethod
    def valid_group(cls, v: str) -> str:
        if v not in GROUPS:
            raise ValueError(f"group must be one of {GROUPS}")
        return v


def participant_view(p: Participant, staff: bool) -> Dict[str, Any]:
    d = {"code": p.code, "group": p.group, "age_range": p.age_range, "handedness": p.handedness,
         "writing_hand": p.writing_hand, "withdrawn": p.withdrawn}
    if staff:
        d["study_site"] = p.study_site
    return d


@router.post("/participants", status_code=201)
def create_participant(body: ParticipantIn, user: User = Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    if body.group in CLINICAL_GROUPS and active_protocol(db) is None:
        raise HTTPException(409, "Clinical participant registration is disabled: no approved research protocol is active")
    p = Participant(code=next_code(db, body.group), group=body.group, age_range=body.age_range,
                    handedness=body.handedness, writing_hand=body.writing_hand, study_site=body.study_site)
    db.add(p); db.flush()
    audit(db, user, "participant.create", p.code); db.commit()
    return participant_view(p, True)


@router.get("/participants")
def list_participants(user: User = Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    return [participant_view(p, True) for p in db.scalars(select(Participant).order_by(Participant.id))]


@router.get("/participants/{code}")
def get_participant(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.scalar(select(Participant).where(Participant.code == code))
    if p is None or not can_access(user, p):
        raise HTTPException(404, "Participant not found")         # 404 (not 403) avoids confirming other IDs exist
    return participant_view(p, user.role in STAFF)


class ClinicalIn(BaseModel):
    diagnosis_confirmed: Optional[bool] = None
    hoehn_yahr: Optional[str] = Field(default=None, max_length=8)
    mds_updrs_motor: Optional[int] = Field(default=None, ge=0, le=132)
    medication_state: Optional[str] = Field(default=None, max_length=64)


@router.put("/participants/{code}/clinical")
def set_clinical(code: str, body: ClinicalIn, user: User = Depends(require_roles("research_admin")),
                 db: Session = Depends(get_db)):
    """Clinician-entered values only. The application never infers these from recordings."""
    p = db.scalar(select(Participant).where(Participant.code == code))
    if p is None:
        raise HTTPException(404, "Participant not found")
    if p.group != "parkinson":
        raise HTTPException(409, "Clinical metadata applies to the Parkinson's group only")
    row = db.scalar(select(ClinicalMetadata).where(ClinicalMetadata.participant_id == p.id))
    if row is None:
        row = ClinicalMetadata(participant_id=p.id, entered_by=user.id); db.add(row)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    row.entered_by, row.entered_at = user.id, utcnow()
    audit(db, user, "clinical.write", p.code); db.commit()
    return {"ok": True}


@router.get("/participants/{code}/clinical")
def get_clinical(code: str, user: User = Depends(require_roles("research_admin")), db: Session = Depends(get_db)):
    p = db.scalar(select(Participant).where(Participant.code == code))
    row = db.scalar(select(ClinicalMetadata).where(ClinicalMetadata.participant_id == p.id)) if p else None
    if row is None:
        raise HTTPException(404, "No clinical metadata")
    audit(db, user, "clinical.read", code); db.commit()
    return {"diagnosis_confirmed": row.diagnosis_confirmed, "hoehn_yahr": row.hoehn_yahr,
            "mds_updrs_motor": row.mds_updrs_motor, "medication_state": row.medication_state}


@router.post("/participants/{code}/withdraw")
def withdraw(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.scalar(select(Participant).where(Participant.code == code))
    if p is None or not (user.participant_id == p.id or user.role in ("research_admin", "system_admin")):
        raise HTTPException(404, "Participant not found")
    now = utcnow()
    p.withdrawn, p.withdrawn_at = True, now
    for c in db.scalars(select(Consent).where(Consent.participant_id == p.id, Consent.withdrawn_at.is_(None))):
        c.withdrawn_at = now
    audit(db, user, "participant.withdraw", p.code); db.commit()
    # NOTE: data deletion/export-exclusion workflow is NOT implemented yet; withdrawal only blocks new collection.
    return {"withdrawn": True, "data_deleted": False,
            "note": "New collection is blocked. Deletion of existing recordings is pending implementation."}


# ---------------- consent ----------------
class ConsentIn(BaseModel):
    participant_code: Optional[str] = None
    consent_version: str = Field(min_length=1, max_length=64)
    consent_recording: bool
    consent_video: bool = False
    consent_data_sharing: bool = False


@router.post("/consent", status_code=201)
def give_consent(body: ConsentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.participant_code:
        p = db.scalar(select(Participant).where(Participant.code == body.participant_code))
        if p is None or not can_access(user, p):
            raise HTTPException(404, "Participant not found")
    else:
        p = own_participant(user, db)
    if p.withdrawn:
        raise HTTPException(409, "Participant has withdrawn")
    pr = active_protocol(db)
    c = Consent(participant_id=p.id, consent_version=body.consent_version, protocol_version=pr.version if pr else None,
                consent_recording=body.consent_recording, consent_video=body.consent_video,
                consent_data_sharing=body.consent_data_sharing)
    db.add(c); audit(db, user, "consent.give", p.code, {"version": body.consent_version}); db.commit()
    return {"consent_id": c.id}


def valid_consent(db: Session, p: Participant) -> Optional[Consent]:
    return db.scalars(select(Consent).where(Consent.participant_id == p.id, Consent.consent_recording.is_(True),
                                            Consent.withdrawn_at.is_(None)).order_by(Consent.id.desc())).first()


# ---------------- sessions ----------------
class SessionIn(BaseModel):
    participant_code: Optional[str] = None
    device_info: Optional[Dict[str, Any]] = None


@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = (db.scalar(select(Participant).where(Participant.code == body.participant_code)) if body.participant_code
         else own_participant(user, db))
    if p is None or not can_access(user, p):
        raise HTTPException(404, "Participant not found")
    if p.withdrawn:
        raise HTTPException(409, "Participant has withdrawn")
    consent = valid_consent(db, p)
    if consent is None:
        raise HTTPException(409, "Recording requires valid recording consent")
    if p.group in CLINICAL_GROUPS:
        pr = active_protocol(db)
        if pr is None:
            raise HTTPException(409, "Clinical recording is disabled: no approved research protocol is active")
        if consent.consent_version != pr.consent_version:
            raise HTTPException(409, "Consent was given for a different consent version; re-consent required")
        mode, pv = "research", pr.version
    else:
        mode, pv = "pilot", None
    n = db.scalar(select(func.count()).select_from(RecordingSession).where(RecordingSession.participant_id == p.id)) or 0
    s = RecordingSession(session_code=f"{p.code}-S{n + 1:03d}", participant_id=p.id, mode=mode,
                         protocol_version=pv, device_info=body.device_info)
    db.add(s); audit(db, user, "session.create", s.session_code); db.commit()
    return {"session_code": s.session_code, "mode": mode,
            "label": "Nonclinical testing only - not clinical validation" if mode == "pilot" else None}


# ---------------- recordings ----------------
class UploadIn(BaseModel):
    session_code: str
    task_type: str
    intended_label: str = Field(min_length=1, max_length=255)
    frames: List[Dict[str, Any]] = Field(min_length=1, max_length=60000)
    device_info: Optional[Dict[str, Any]] = None
    timestamp_source: str = "unknown"
    mirrored_preview: bool = False

    @field_validator("task_type")
    @classmethod
    def task_ok(cls, v: str) -> str:
        if v not in TASKS:
            raise ValueError(f"task_type must be one of {TASKS}")
        return v


@router.post("/recordings/upload", status_code=201)
def upload_recording(body: UploadIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Store raw captured frames verbatim (landmarks + timestamps) and derived stroke/quality files next to them.
    The intended label is the PROMPTED label; any model prediction is stored separately and never as ground truth."""
    s = db.scalar(select(RecordingSession).where(RecordingSession.session_code == body.session_code))
    p = db.get(Participant, s.participant_id) if s else None
    if s is None or not can_access(user, p):
        raise HTTPException(404, "Session not found")
    if p.withdrawn or valid_consent(db, p) is None:
        raise HTTPException(409, "Recording requires valid recording consent")
    if s.status != "open":
        raise HTTPException(409, "Session is closed")
    if s.mode == "research" and active_protocol(db) is None:
        raise HTTPException(409, "Research recording is disabled: no approved research protocol is active")
    n = db.scalar(select(func.count()).select_from(Recording).where(Recording.session_id == s.id)) or 0
    rec_code = f"rec_{n + 1:04d}"
    folder = {"parkinson": "Parkinson_Group", "healthy_control": "Healthy_Control_Group",
              "pilot_nonclinical": "Pilot_Nonclinical"}[p.group]
    rel = os.path.join(folder, p.code, s.session_code, rec_code)
    out_dir = os.path.join(get_settings().data_dir, rel)
    cap = CaptureSession(p.code, s.session_code, body.intended_label, device_info=body.device_info or s.device_info,
                         mirrored_preview=body.mirrored_preview, timestamp_source=body.timestamp_source)
    cap.start()
    for fr in body.frames:
        cap.add_frame(fr)
    cap.save(out_dir)
    meta = json.load(open(os.path.join(out_dir, "recording_meta.json")))
    r = Recording(session_id=s.id, participant_id=p.id, task_type=body.task_type, intended_label=body.intended_label,
                  storage_path=rel, is_synthetic=False, meta={"timestamp_quality": meta["timestamp_quality"],
                  "tracking_failure_rate": meta["tracking_failure_rate"], "n_frames": meta["n_frames"]})
    db.add(r); db.flush(); audit(db, user, "recording.upload", f"{s.session_code}/{rec_code}"); db.commit()
    return {"recording_id": r.id, "storage_path": rel, "n_frames": meta["n_frames"],
            "timestamp_quality": meta["timestamp_quality"]}


def recording_view(r: Recording, staff: bool) -> Dict[str, Any]:
    d = {"id": r.id, "task_type": r.task_type, "intended_label": r.intended_label,
         "participant_confirmed_label": r.participant_confirmed_label, "predicted_label": r.predicted_label,
         "prediction_confidence": r.prediction_confidence, "is_synthetic": r.is_synthetic, "meta": r.meta}
    if staff:
        d.update({"researcher_verified_label": r.researcher_verified_label, "quality_status": r.quality_status,
                  "quality_reason": r.quality_reason})
    return d


@router.get("/recordings/{rid}")
def get_recording(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Recording, rid)
    p = db.get(Participant, r.participant_id) if r else None
    if r is None or not can_access(user, p):
        raise HTTPException(404, "Recording not found")
    return recording_view(r, user.role in STAFF)


class LabelIn(BaseModel):
    participant_confirmed_label: Optional[str] = Field(default=None, max_length=255)
    researcher_verified_label: Optional[str] = Field(default=None, max_length=255)


@router.patch("/recordings/{rid}/labels")
def set_labels(rid: int, body: LabelIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Each change is logged as a LabelRevision. intended_label and predicted_label are immutable here."""
    r = db.get(Recording, rid)
    p = db.get(Participant, r.participant_id) if r else None
    if r is None or not can_access(user, p):
        raise HTTPException(404, "Recording not found")
    changes = body.model_dump(exclude_unset=True)
    if "researcher_verified_label" in changes and user.role not in STAFF:
        raise HTTPException(403, "Only researchers can set the researcher-verified label")
    for field, new in changes.items():
        old = getattr(r, field)
        if old != new:
            db.add(LabelRevision(recording_id=r.id, field=field, old_value=old, new_value=new, changed_by=user.id))
            setattr(r, field, new)
    audit(db, user, "label.update", str(rid), {"fields": list(changes)}); db.commit()
    return recording_view(r, user.role in STAFF)


@router.get("/dataset/statistics")
def dataset_statistics(user: User = Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    """Counts computed live from the database -- no hardcoded numbers."""
    by_group = dict(db.execute(select(Participant.group, func.count()).group_by(Participant.group)).all())
    by_task = dict(db.execute(select(Recording.task_type, func.count()).group_by(Recording.task_type)).all())
    return {"participants_by_group": by_group, "recordings_by_task": by_task,
            "sessions": db.scalar(select(func.count()).select_from(RecordingSession)) or 0,
            "recordings_total": db.scalar(select(func.count()).select_from(Recording)) or 0,
            "synthetic_recordings": db.scalar(select(func.count()).select_from(Recording).where(Recording.is_synthetic.is_(True))) or 0}
