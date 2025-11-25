from app.database import Base
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = "users"
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email = Column(String, unique=True, nullable=False)
    user_name = Column(String)
    user_avatar = Column(String)
    is_verified = Column(Integer, default=0)  # 0 = False, 1 = True

    auth = relationship("Auth", back_populates="user", uselist=False)
    refresh_tokens = relationship("RefreshToken", back_populates="user")

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
    reftok_id = Column(Integer, primary_key=True, autoincrement=True)
    reftok_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"))
    reftok_token = Column(String, unique=True, nullable=False)
    reftok_expires_at = Column(DateTime, nullable=False)
    reftok_revoked_at = Column(DateTime, nullable=True)
    reftok_issued_from_ip = Column(String(45))

    user = relationship("User", back_populates="refresh_tokens")