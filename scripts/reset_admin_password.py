from app.auth.security import hash_password
from app.db.database import SessionLocal
from app.db.models import UserORM


def main() -> None:
    db = SessionLocal()
    try:
        admin = db.query(UserORM).filter(UserORM.username == "admin").first()
        if admin is None:
            admin = UserORM(
                username="admin",
                full_name="Administrator",
                role="admin",
                password_hash=hash_password("admin123"),
                is_active=True,
            )
            db.add(admin)
        else:
            admin.full_name = admin.full_name or "Administrator"
            admin.role = "admin"
            admin.password_hash = hash_password("admin123")
            admin.is_active = True
            db.add(admin)

        db.commit()
        print("Admin password reset to admin123")
    finally:
        db.close()


if __name__ == "__main__":
    main()
