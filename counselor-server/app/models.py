import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Boolean, ForeignKey, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(20), default="counselor")
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    mfa_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_pending: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_pending_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_last_step: Mapped[int] = mapped_column(Integer, default=-1)
    recovery_hashes: Mapped[str] = mapped_column(Text, default="[]")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_backup: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
class Student(Base):
    __tablename__ = "students"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    classroom: Mapped[str] = mapped_column(Text)
    referral: Mapped[str] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_recorded: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="planned")
class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="open")

class StudentShare(Base):
    __tablename__ = "student_shares"
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
class AIConfig(Base):
    __tablename__ = "ai_configs"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    key: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    transcription_model: Mapped[str] = mapped_column(String(120))
    summary_model: Mapped[str] = mapped_column(String(120))
class BackupImport(Base):
    __tablename__ = "backup_imports"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
