from app.database import Base
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean, Enum
import enum
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import relationship

class UserRole(enum.Enum):
    CLIENT_ADMIN = "CLIENT_ADMIN"
    CLIENT_USER = "CLIENT_USER"

class User(Base):
    __tablename__ = "users"
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email = Column(String, unique=True, nullable=False)
    user_name = Column(String)
    user_avatar = Column(String)
    user_is_verified = Column(Boolean, default=False) 
    user_company_id = Column(UUID(as_uuid=True),
                             ForeignKey("companies.company_id", ondelete="CASCADE"),  nullable=True)
    user_role = Column(Enum(UserRole), default=UserRole.CLIENT_ADMIN, nullable=False)

    auth = relationship("Auth", back_populates="user", uselist=False)
    refresh_tokens = relationship("RefreshToken", back_populates="user")
    email_verifications = relationship("EmailVerification", back_populates="user")
    company = relationship("Company", back_populates="users")

class Company(Base):
    __tablename__ = "companies"
    company_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String)

    users = relationship("User", back_populates="company")

class Auth(Base):
    __tablename__ = "authentication"
    auth_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True)
    auth_password_hash = Column(String, nullable=False)
    auth_failed_login_attempts = Column(Integer, default=0, nullable=False)
    auth_is_locked_until = Column(DateTime, nullable=True)
    auth_password_updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="auth")

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    rftk_id = Column(Integer, primary_key=True, autoincrement=True)
    rftk_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    rftk_token = Column(String, unique=True, nullable=False)
    rftk_expires_at = Column(DateTime, nullable=False)
    rftk_revoked_at = Column(DateTime, nullable=True)
    rftk_issued_from_ip = Column(String(45))

    user = relationship("User", back_populates="refresh_tokens")


class EmailVerification(Base):
    __tablename__ = "email_verifications"
    emvr_token_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    emvr_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    emvr_token = Column(String, unique=True, nullable=False)
    emvr_expires_at = Column(DateTime, nullable=False, default=lambda: datetime.utcnow() + timedelta(hours=24))

    user = relationship("User", back_populates="email_verifications")