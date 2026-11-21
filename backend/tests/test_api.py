import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.pool import StaticPool

FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "landmark_fixtures.json")))
FRAMES = FX["sequences"][0]["frames"]
PW = "correct-horse-battery"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("PARKISCRIBE_DATA_DIR", str(tmp_path / "store"))
    from app.database import session as dbs
    from app.database.models import Base
    eng = dbs.configure("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(eng)
    from app.main import create_app
    client = TestClient(create_app(create_tables=False))
    return client, dbs


def make_user(dbs, email, role, participant_code=None):
    from app.database.models import Participant, User
    from app.security.auth import hash_password
    gen = dbs.get_db(); db = next(gen)
    pid = None
    if participant_code:
        p = db.scalar(select(Participant).where(Participant.code == participant_code))
        pid = p.id
    db.add(User(email=email, password_hash=hash_password(PW), role=role, participant_id=pid)); db.commit()
    gen.close()


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def activate(client, h, consent_version="C1"):
    return client.post("/api/admin/protocol/activate", headers=h, json={
        "version": "P1", "ethics_committee": "Test IEC (unit test)", "ethics_reference": "TEST-REF-0001",
        "approval_date": "2026-01-01", "consent_version": consent_version})


def test_register_creates_pilot_participant_only_and_login_works(env):
    c, _ = env
    r = c.post("/api/auth/register", json={"email": "a@example.com", "password": PW})
    assert r.status_code == 201 and r.json()["role"] == "participant" and r.json()["participant_code"].startswith("PILOT")
    assert c.post("/api/auth/register", json={"email": "a@example.com", "password": PW}).status_code == 409
    assert c.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password"}).status_code == 401
    h = login(c, "a@example.com")
    assert c.get("/api/auth/me", headers=h).json()["participant_code"].startswith("PILOT")


def test_register_cannot_choose_role_or_group(env):
    c, _ = env
    r = c.post("/api/auth/register", json={"email": "b@example.com", "password": PW, "role": "system_admin", "group": "parkinson"})
    assert r.status_code == 201 and r.json()["role"] == "participant" and r.json()["participant_code"].startswith("PILOT")


def test_short_password_rejected(env):
    c, _ = env
    assert c.post("/api/auth/register", json={"email": "c@example.com", "password": "short"}).status_code == 422


def test_unauthenticated_and_bad_token_rejected(env):
    c, _ = env
    assert c.get("/api/auth/me").status_code == 401
    assert c.get("/api/participants", headers={"Authorization": "Bearer not.a.token"}).status_code == 401


def test_first_install_protocol_inactive_pilot_only(env):
    c, _ = env
    s = c.get("/api/protocol/status").json()
    assert s["protocol_active"] is False and s["clinical_collection_enabled"] is False and s["pilot_mode_available"] is True


def test_clinical_registration_blocked_until_protocol_activated(env):
    c, dbs = env
    make_user(dbs, "res@example.com", "researcher"); make_user(dbs, "adm@example.com", "research_admin")
    hr, ha = login(c, "res@example.com"), login(c, "adm@example.com")
    assert c.post("/api/participants", headers=hr, json={"group": "parkinson"}).status_code == 409
    assert c.post("/api/participants", headers=hr, json={"group": "healthy_control"}).status_code == 409
    assert c.post("/api/participants", headers=hr, json={"group": "pilot_nonclinical"}).status_code == 201
    assert activate(c, ha).status_code == 201
    r = c.post("/api/participants", headers=hr, json={"group": "parkinson"})
    assert r.status_code == 201 and r.json()["code"] == "PD001"


def test_only_research_admin_can_activate_and_ethics_fields_required(env):
    c, dbs = env
    make_user(dbs, "res@example.com", "researcher"); make_user(dbs, "sys@example.com", "system_admin")
    make_user(dbs, "adm@example.com", "research_admin")
    assert activate(c, login(c, "res@example.com")).status_code == 403
    assert activate(c, login(c, "sys@example.com")).status_code == 403
    assert c.post("/api/admin/protocol/activate").status_code in (401, 403)
    ha = login(c, "adm@example.com")
    for blank in ("ethics_committee", "ethics_reference", "approval_date"):
        body = {"version": "P1", "ethics_committee": "Test IEC", "ethics_reference": "TEST-1", "approval_date": "2026-01-01",
                "consent_version": "C1", blank: "        "}
        assert c.post("/api/admin/protocol/activate", headers=ha, json=body).status_code == 422
    assert c.get("/api/protocol/status").json()["protocol_active"] is False
    assert activate(c, ha).status_code == 201
    assert c.get("/api/protocol/status").json()["protocol_active"] is True


def test_participant_cannot_access_staff_endpoints_or_other_participants(env):
    c, _ = env
    c.post("/api/auth/register", json={"email": "p1@example.com", "password": PW})
    c.post("/api/auth/register", json={"email": "p2@example.com", "password": PW})
    h1 = login(c, "p1@example.com")
    assert c.get("/api/participants", headers=h1).status_code == 403
    assert c.get("/api/dataset/statistics", headers=h1).status_code == 403
    assert c.get("/api/admin/audit-log", headers=h1).status_code == 403
    assert c.get("/api/participants/PILOT002", headers=h1).status_code == 404     # someone else's record
    assert c.get("/api/participants/PILOT001", headers=h1).status_code == 200


def test_clinical_metadata_restricted_to_research_admin(env):
    c, dbs = env
    make_user(dbs, "res@example.com", "researcher"); make_user(dbs, "adm@example.com", "research_admin")
    hr, ha = login(c, "res@example.com"), login(c, "adm@example.com")
    activate(c, ha)
    code = c.post("/api/participants", headers=hr, json={"group": "parkinson"}).json()["code"]
    body = {"diagnosis_confirmed": True, "hoehn_yahr": "2", "mds_updrs_motor": 20}
    assert c.put(f"/api/participants/{code}/clinical", headers=hr, json=body).status_code == 403
    assert c.get(f"/api/participants/{code}/clinical", headers=hr).status_code == 403
    assert c.put(f"/api/participants/{code}/clinical", headers=ha, json=body).status_code == 200
    assert c.get(f"/api/participants/{code}/clinical", headers=ha).json()["hoehn_yahr"] == "2"
    pc = c.post("/api/participants", headers=hr, json={"group": "healthy_control"}).json()["code"]
    assert c.put(f"/api/participants/{pc}/clinical", headers=ha, json=body).status_code == 409
    # participant view never contains clinical fields
    assert "hoehn_yahr" not in json.dumps(c.get(f"/api/participants/{code}", headers=hr).json())


def test_session_requires_consent_then_pilot_mode_works(env):
    c, _ = env
    c.post("/api/auth/register", json={"email": "p@example.com", "password": PW})
    h = login(c, "p@example.com")
    assert c.post("/api/sessions", headers=h, json={}).status_code == 409                # no consent yet
    assert c.post("/api/consent", headers=h, json={"consent_version": "PILOT-1", "consent_recording": False}).status_code == 201
    assert c.post("/api/sessions", headers=h, json={}).status_code == 409                # declined recording
    assert c.post("/api/consent", headers=h, json={"consent_version": "PILOT-1", "consent_recording": True}).status_code == 201
    r = c.post("/api/sessions", headers=h, json={"device_info": {"ua": "test"}})
    assert r.status_code == 201 and r.json()["mode"] == "pilot" and "Nonclinical" in r.json()["label"]


def test_clinical_session_requires_active_protocol_and_matching_consent_version(env):
    c, dbs = env
    make_user(dbs, "res@example.com", "researcher"); make_user(dbs, "adm@example.com", "research_admin")
    hr, ha = login(c, "res@example.com"), login(c, "adm@example.com")
    activate(c, ha, consent_version="C1")
    code = c.post("/api/participants", headers=hr, json={"group": "healthy_control"}).json()["code"]
    assert c.post("/api/sessions", headers=hr, json={"participant_code": code}).status_code == 409   # no consent
    c.post("/api/consent", headers=hr, json={"participant_code": code, "consent_version": "OLD", "consent_recording": True})
    assert c.post("/api/sessions", headers=hr, json={"participant_code": code}).status_code == 409   # wrong consent version
    c.post("/api/consent", headers=hr, json={"participant_code": code, "consent_version": "C1", "consent_recording": True})
    r = c.post("/api/sessions", headers=hr, json={"participant_code": code})
    assert r.status_code == 201 and r.json()["mode"] == "research"
    activate(c, ha, consent_version="C2")                                                       # new consent version
    assert c.post("/api/sessions", headers=hr, json={"participant_code": code}).status_code == 409


def pilot_session(c):
    c.post("/api/auth/register", json={"email": "p@example.com", "password": PW})
    h = login(c, "p@example.com")
    c.post("/api/consent", headers=h, json={"consent_version": "PILOT-1", "consent_recording": True})
    return h, c.post("/api/sessions", headers=h, json={}).json()["session_code"]


def test_upload_stores_raw_frames_and_separates_labels(env, tmp_path):
    c, _ = env
    h, sc = pilot_session(c)
    r = c.post("/api/recordings/upload", headers=h, json={"session_code": sc, "task_type": "character",
               "intended_label": "A", "frames": FRAMES, "timestamp_source": "constructed"})
    assert r.status_code == 201, r.text
    d = r.json()
    base = os.path.join(str(tmp_path / "store"), d["storage_path"])
    raw = json.load(open(os.path.join(base, "raw_landmarks.json")))["frames"]
    assert len(raw) == len(FRAMES) and len(raw[0]["hands"][0]["landmarks"]) == 21
    assert d["timestamp_quality"]["n_dropped_suspected"] == 2
    rec = c.get(f"/api/recordings/{d['recording_id']}", headers=h).json()
    assert rec["intended_label"] == "A" and rec["predicted_label"] is None and rec["participant_confirmed_label"] is None
    assert "PILOT001" in d["storage_path"] and "researcher_verified_label" not in rec


def test_upload_rejected_after_withdrawal_and_without_consent(env):
    c, _ = env
    h, sc = pilot_session(c)
    assert c.post("/api/participants/PILOT001/withdraw", headers=h).json()["withdrawn"] is True
    r = c.post("/api/recordings/upload", headers=h, json={"session_code": sc, "task_type": "character",
               "intended_label": "A", "frames": FRAMES})
    assert r.status_code == 409
    assert c.post("/api/sessions", headers=h, json={}).status_code == 409


def test_upload_validation(env):
    c, _ = env
    h, sc = pilot_session(c)
    bad_task = c.post("/api/recordings/upload", headers=h, json={"session_code": sc, "task_type": "nope", "intended_label": "A", "frames": FRAMES})
    no_frames = c.post("/api/recordings/upload", headers=h, json={"session_code": sc, "task_type": "character", "intended_label": "A", "frames": []})
    no_label = c.post("/api/recordings/upload", headers=h, json={"session_code": sc, "task_type": "character", "intended_label": "", "frames": FRAMES})
    assert bad_task.status_code == no_frames.status_code == no_label.status_code == 422
    assert c.post("/api/recordings/upload", headers=h, json={"session_code": "NOPE-S001", "task_type": "character", "intended_label": "A", "frames": FRAMES}).status_code == 404


def test_other_participant_cannot_read_or_upload(env):
    c, _ = env
    h1, sc1 = pilot_session(c)
    rid = c.post("/api/recordings/upload", headers=h1, json={"session_code": sc1, "task_type": "character", "intended_label": "A", "frames": FRAMES}).json()["recording_id"]
    c.post("/api/auth/register", json={"email": "other@example.com", "password": PW})
    h2 = login(c, "other@example.com")
    assert c.get(f"/api/recordings/{rid}", headers=h2).status_code == 404
    assert c.patch(f"/api/recordings/{rid}/labels", headers=h2, json={"participant_confirmed_label": "Z"}).status_code == 404
    assert c.post("/api/recordings/upload", headers=h2, json={"session_code": sc1, "task_type": "character", "intended_label": "A", "frames": FRAMES}).status_code == 404


def test_label_corrections_are_audited_and_do_not_touch_intended_or_prediction(env):
    c, dbs = env
    h, sc = pilot_session(c)
    rid = c.post("/api/recordings/upload", headers=h, json={"session_code": sc, "task_type": "character", "intended_label": "A", "frames": FRAMES}).json()["recording_id"]
    r = c.patch(f"/api/recordings/{rid}/labels", headers=h, json={"participant_confirmed_label": "B"})
    assert r.status_code == 200 and r.json()["intended_label"] == "A" and r.json()["participant_confirmed_label"] == "B"
    assert c.patch(f"/api/recordings/{rid}/labels", headers=h, json={"researcher_verified_label": "B"}).status_code == 403
    make_user(dbs, "res@example.com", "researcher")
    hr = login(c, "res@example.com")
    r2 = c.patch(f"/api/recordings/{rid}/labels", headers=hr, json={"researcher_verified_label": "A"})
    assert r2.json()["researcher_verified_label"] == "A" and r2.json()["participant_confirmed_label"] == "B"
    from app.database.models import LabelRevision
    gen = dbs.get_db(); db = next(gen)
    revs = db.scalars(select(LabelRevision).where(LabelRevision.recording_id == rid)).all()
    assert [(x.field, x.old_value, x.new_value) for x in revs] == [("participant_confirmed_label", None, "B"), ("researcher_verified_label", None, "A")]
    gen.close()


def test_audit_log_records_actions_and_is_admin_only(env):
    c, dbs = env
    make_user(dbs, "adm@example.com", "research_admin")
    c.post("/api/auth/register", json={"email": "p@example.com", "password": PW})
    ha = login(c, "adm@example.com")
    actions = [a["action"] for a in c.get("/api/admin/audit-log", headers=ha).json()]
    assert "auth.register" in actions and "auth.login" in actions


def test_dataset_statistics_are_computed_not_hardcoded(env):
    c, dbs = env
    make_user(dbs, "res@example.com", "researcher")
    hr = login(c, "res@example.com")
    s0 = c.get("/api/dataset/statistics", headers=hr).json()
    assert s0["recordings_total"] == 0 and s0["participants_by_group"] == {}
    h, sc = pilot_session(c)
    c.post("/api/recordings/upload", headers=h, json={"session_code": sc, "task_type": "word", "intended_label": "HELP", "frames": FRAMES})
    s1 = c.get("/api/dataset/statistics", headers=hr).json()
    assert s1["recordings_total"] == 1 and s1["recordings_by_task"] == {"word": 1} and s1["synthetic_recordings"] == 0


def test_token_without_secret_configured_fails_safely(env, monkeypatch):
    c, dbs = env
    make_user(dbs, "res@example.com", "researcher")
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(RuntimeError):
        c.post("/api/auth/login", json={"email": "res@example.com", "password": PW})
