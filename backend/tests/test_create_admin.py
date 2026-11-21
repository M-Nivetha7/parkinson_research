from sqlalchemy import select
from sqlalchemy.pool import StaticPool


def test_create_admin_script(monkeypatch):
    from app.database import session as dbs
    from app.database.models import Base, User
    eng = dbs.configure("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(eng)
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-enough-password")
    from scripts.create_admin import main
    assert main(["--email", "Admin@Example.com", "--role", "research_admin"]) == 0
    assert main(["--email", "admin@example.com"]) == 1            # duplicate
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    assert main(["--email", "other@example.com"]) == 2            # weak password
    gen = dbs.get_db(); db = next(gen)
    u = db.scalar(select(User).where(User.email == "admin@example.com"))
    assert u.role == "research_admin" and u.password_hash.startswith("scrypt$") and "a-long" not in u.password_hash
    gen.close()
