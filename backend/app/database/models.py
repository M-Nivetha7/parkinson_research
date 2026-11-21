"""SQLAlchemy models.

Design notes
* Research records use pseudonymous participant codes (PD001 / HC001 / PILOT001) only.
* Contact details live in a SEPARATE table (``participant_contacts``) that no participant/researcher endpoint reads.
* Clinical metadata lives in its own table, written only by research administrators.
* Ground truth (intended / participant-confirmed / researcher-verified) and model predictions are separate columns;
  nothing is ever overwritten -- corrections are new rows in ``label_revisions``.
"""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ROLES = ("participant", "researcher", "research_admin", "system_admin")
GROUPS = ("parkinson", "healthy_control", "pilot_nonclinical")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="participant")
    participant_id: Mapped[int | None] = mapped_column(ForeignKey("participants.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Protocol(Base):
    """Research protocol. Clinical collection requires status == 'active' AND ethics details recorded by an admin."""
    __tablename__ = "protocols"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="inactive")      # inactive | active | retired
    ethics_committee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ethics_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    repetitions_per_character: Mapped[int] = mapped_column(Integer, default=3)
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Participant(Base):
    __tablename__ = "participants"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)   # PD001 / HC001 / PILOT001
    group: Mapped[str] = mapped_column(String(32))
    age_range: Mapped[str | None] = mapped_column(String(16), nullable=True)
    handedness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    writing_hand: Mapped[str | None] = mapped_column(String(16), nullable=True)
    study_site: Mapped[str | None] = mapped_column(String(128), nullable=True)
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParticipantContact(Base):
    """Identity key -- kept apart from research data; no API in this build reads it."""
    __tablename__ = "participant_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), unique=True)
    contact_encrypted: Mapped[str] = mapped_column(Text)


class ClinicalMetadata(Base):
    __tablename__ = "clinical_metadata"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), unique=True)
    diagnosis_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hoehn_yahr: Mapped[str | None] = mapped_column(String(8), nullable=True)      # clinician-entered only
    mds_updrs_motor: Mapped[int | None] = mapped_column(Integer, nullable=True)   # clinician-entered only
    medication_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entered_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    consent_version: Mapped[str] = mapped_column(String(64))
    protocol_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_recording: Mapped[bool] = mapped_column(Boolean)           # movement-data recording
    consent_video: Mapped[bool] = mapped_column(Boolean, default=False)  # separate, optional
    consent_data_sharing: Mapped[bool] = mapped_column(Boolean, default=False)
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecordingSession(Base):
    __tablename__ = "recording_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_code: Mapped[str] = mapped_column(String(32), unique=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16))                 # pilot | research
    protocol_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("recording_sessions.id"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(16))            # character | word | sentence | freeform
    intended_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    participant_confirmed_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    researcher_verified_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    predicted_label: Mapped[str | None] = mapped_column(String(255), nullable=True)   # never overwritten
    prediction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(512))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_status: Mapped[str] = mapped_column(String(16), default="unreviewed")
    quality_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LabelRevision(Base):
    __tablename__ = "label_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[int] = mapped_column(ForeignKey("recordings.id"), index=True)
    field: Mapped[str] = mapped_column(String(32))
    old_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
