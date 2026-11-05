from sqlalchemy import ForeignKey, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class StaffORM(Base):
    __tablename__ = "uks_staff"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(25), default="")


class StaffVisitORM(Base):
    __tablename__ = "uks_staff_visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("uks_staff.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    visit_date: Mapped[str] = mapped_column(String(10), index=True)
    record: Mapped[dict] = mapped_column(JSON)
    whatsapp_status: Mapped[str] = mapped_column(String(20))
