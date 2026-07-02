from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import parse_access_token
from app.db.dependencies import get_db
from app.db.models import UserORM

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserORM:
    user_id = None
    if credentials is not None:
        token = credentials.credentials
        try:
            payload = parse_access_token(token)
            user_id = payload.get("sub")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    else:
        session_user = request.session.get("user") if hasattr(request, "session") else None
        if session_user:
            user_id = session_user.get("id")

    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    user = db.get(UserORM, int(user_id)) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


def require_roles(*allowed_roles: str):
    def _dependency(current_user: UserORM = Depends(get_current_user)) -> UserORM:
        expanded_roles = set(allowed_roles)
        if "perawat" in expanded_roles:
            expanded_roles.update({"kepala_sekolah", "tim_uksr"})
        if current_user.role not in expanded_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return current_user

    return _dependency
