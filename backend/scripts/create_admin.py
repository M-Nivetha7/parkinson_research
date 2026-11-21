"""Create a staff account (default role: research_admin). Run from the backend folder:

    export JWT_SECRET=...   # not needed here, but the app needs it later
    python -m scripts.create_admin --email you@example.com --role research_admin

The password is read from the ADMIN_PASSWORD environment variable or prompted; it is never a command-line argument.
"""
import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.database.models import Base, ROLES, User
from app.database import session as dbs
from app.security.auth import hash_password


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--role", default="research_admin", choices=[r for r in ROLES if r != "participant"])
    a = ap.parse_args(argv)
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password (min 10 chars): ")
    if len(pw) < 10:
        print("Password must be at least 10 characters.", file=sys.stderr)
        return 2
    eng = dbs.get_engine()
    Base.metadata.create_all(eng)
    gen = dbs.get_db()
    db = next(gen)
    try:
        email = a.email.lower()
        if db.scalar(select(User).where(User.email == email)):
            print("A user with that email already exists.", file=sys.stderr)
            return 1
        db.add(User(email=email, password_hash=hash_password(pw), role=a.role))
        db.commit()
        print(f"Created {a.role} account for {email}")
        return 0
    finally:
        gen.close()


if __name__ == "__main__":
    raise SystemExit(main())
