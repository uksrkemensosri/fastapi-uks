import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.auth.security import hash_password
from app.db.database import SessionLocal
from app.db.models import UserORM


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else os.getenv("SUPER_ADMIN_USERNAME", "superadmin")
    password = sys.argv[2] if len(sys.argv) > 2 else os.getenv("SUPER_ADMIN_PASSWORD", "superadmin123")
    full_name = os.getenv("SUPER_ADMIN_FULL_NAME", "Super Administrator")

    db = SessionLocal()
    try:
        user = db.query(UserORM).filter(UserORM.username == username).first()
        if user is None:
            user = UserORM(
                username=username,
                full_name=full_name,
                role="super_admin",
                password_hash=hash_password(password),
                is_active=True,
                school_id=None,
            )
            db.add(user)
            action = "created"
        else:
            user.full_name = user.full_name or full_name
            user.role = "super_admin"
            user.password_hash = hash_password(password)
            user.is_active = True
            user.school_id = None
            action = "updated"
        db.commit()
        print(f"Super admin {action}: {username}")
        print(f"Password: {password}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
