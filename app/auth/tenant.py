from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Query, Session

from app.db.models import SchoolORM, UserORM

ROLE_SUPER_ADMIN = "super_admin"
DEFAULT_SCHOOL_CODE = "SR-DEMO"
DEFAULT_SCHOOL_NAME = "Sekolah Rakyat Demo"

ModelT = TypeVar("ModelT")


def is_super_admin(user: UserORM) -> bool:
    return user.role == ROLE_SUPER_ADMIN


def get_default_school(db: Session) -> SchoolORM:
    school = db.query(SchoolORM).filter(SchoolORM.school_code == DEFAULT_SCHOOL_CODE).first()
    if school is None:
        school = SchoolORM(
            school_code=DEFAULT_SCHOOL_CODE,
            school_name=DEFAULT_SCHOOL_NAME,
            is_active=True,
        )
        db.add(school)
        db.flush()
    return school


def require_user_school(user: UserORM) -> int:
    if user.school_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not assigned to a school",
        )
    return user.school_id


def tenant_query(query: Query, model: type[ModelT], user: UserORM) -> Query:
    if is_super_admin(user):
        return query
    return query.filter(model.school_id == require_user_school(user))


def tenant_get(db: Session, model: type[ModelT], object_id, user: UserORM) -> ModelT | None:
    item = db.get(model, object_id)
    if item is None:
        return None
    if is_super_admin(user):
        return item
    if getattr(item, "school_id", None) != require_user_school(user):
        return None
    return item


def assign_school(item: object, user: UserORM, explicit_school_id: int | None = None) -> None:
    if is_super_admin(user):
        setattr(item, "school_id", explicit_school_id)
    else:
        setattr(item, "school_id", require_user_school(user))

