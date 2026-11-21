"""Password hashing (stdlib scrypt), JWT issuing/verification, and backend-enforced role checks."""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..database.models import User
from ..database.session import get_db

_bearer = HTTPBearer(auto_error=False)
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        salt, want = base64.b64decode(s), base64.b64decode(h)
    except Exception:
        return False
    got = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return hmac.compare_digest(got, want)


def create_token(user: User) -> str:
    st = get_settings()
    if not st.jwt_secret or len(st.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must be set to at least 32 characters")
    exp = datetime.now(timezone.utc) + timedelta(minutes=st.jwt_ttl_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, st.jwt_secret, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    st = get_settings()
    try:
        payload = jwt.decode(cred.credentials, st.jwt_secret, algorithms=["HS256"])
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, uid)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or inactive user")
    return user      # role is read from the DB, not trusted from the token


def require_roles(*roles: str) -> Callable:
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user
    return dep
