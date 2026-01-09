"""
Client Portal Authentication Helpers

Provides authentication utilities for client portal users,
separate from the internal admin user authentication.
"""

from datetime import datetime, timedelta
from typing import List, Optional
import secrets
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from app.database import get_db
from app.models import ClientUser, ClientRefreshToken, Site, AddressBook
from app.config import settings
from app.utils.security import verify_password, get_password_hash

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Client token settings
CLIENT_TOKEN_PREFIX = "client:"  # Prefix in JWT subject to distinguish client tokens
CLIENT_REFRESH_TOKEN_EXPIRE_DAYS = 7
CLIENT_INVITATION_EXPIRE_DAYS = 7


def create_client_access_token(client_user: ClientUser, expires_delta: Optional[timedelta] = None) -> str:
    """Create an access token for a client user with 'client:' prefix in subject"""
    to_encode = {
        "sub": f"{CLIENT_TOKEN_PREFIX}{client_user.email}",
        "client_id": client_user.id,
        "company_id": client_user.company_id,
        "type": "client"
    }
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def verify_client_token(token: str) -> Optional[dict]:
    """
    Verify a client access token and return payload.
    Returns None if invalid or not a client token.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        subject: str = payload.get("sub")

        # Check if it's a client token
        if subject is None or not subject.startswith(CLIENT_TOKEN_PREFIX):
            return None

        # Extract email from subject
        email = subject[len(CLIENT_TOKEN_PREFIX):]
        return {
            "email": email,
            "client_id": payload.get("client_id"),
            "company_id": payload.get("company_id"),
            "type": payload.get("type")
        }
    except JWTError:
        return None


def generate_client_refresh_token() -> str:
    """Generate a secure random refresh token for client"""
    return secrets.token_urlsafe(64)


def get_client_refresh_token_expiry() -> datetime:
    """Get the expiry datetime for a client refresh token"""
    return datetime.utcnow() + timedelta(days=CLIENT_REFRESH_TOKEN_EXPIRE_DAYS)


def generate_invitation_token() -> str:
    """Generate a secure random invitation token"""
    return secrets.token_urlsafe(32)


def get_invitation_token_expiry() -> datetime:
    """Get the expiry datetime for an invitation token"""
    return datetime.utcnow() + timedelta(days=CLIENT_INVITATION_EXPIRE_DAYS)


async def get_current_client(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> ClientUser:
    """
    Validate client JWT token and return client user.
    Similar to get_current_user but for client portal.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        logger.error("[get_current_client] No credentials provided")
        raise credentials_exception

    payload = verify_client_token(credentials.credentials)
    if payload is None:
        logger.error("[get_current_client] Token verification failed")
        raise credentials_exception

    client_id = payload.get("client_id")
    if client_id is None:
        logger.error("[get_current_client] No client_id in token")
        raise credentials_exception

    client = db.query(ClientUser).filter(ClientUser.id == client_id).first()
    if client is None:
        logger.error(f"[get_current_client] Client not found for id: {client_id}")
        raise credentials_exception

    if not client.is_active:
        logger.error(f"[get_current_client] Client is inactive: {client_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client account is inactive"
        )

    logger.info(f"[get_current_client] Client authenticated: {client.email}")
    return client


def get_client_accessible_site_ids(db: Session, client: ClientUser) -> List[int]:
    """
    Get all site IDs accessible to a client user.

    A client is linked to an AddressBook entry (Customer or Client Branch).
    They can access sites where:
    - Site.address_book_id equals client's address_book_id (direct link)
    - Site.address_book_id links to a CB whose parent_address_book_id equals client's address_book_id

    Company isolation is enforced by:
    - Verifying the client's address_book belongs to the client's company
    - Only including child branches that belong to the same company
    - Joining Sites through AddressBook to verify company_id
    """
    # Get the client's address book entry - verify it belongs to client's company
    client_ab = db.query(AddressBook).filter(
        AddressBook.id == client.address_book_id,
        AddressBook.company_id == client.company_id  # Company isolation
    ).first()
    if not client_ab:
        return []

    # Build list of address_book_ids that the client can access
    accessible_ab_ids = [client.address_book_id]

    # If client is linked to a Customer (C), they can also access sites linked to child branches (CB)
    if client_ab.search_type == 'C':
        # Get all child branches - must belong to same company
        child_branches = db.query(AddressBook.id).filter(
            AddressBook.parent_address_book_id == client.address_book_id,
            AddressBook.search_type == 'CB',
            AddressBook.company_id == client.company_id,  # Company isolation
            AddressBook.is_active == True
        ).all()
        accessible_ab_ids.extend([cb.id for cb in child_branches])

    # Get site IDs linked to any of these address book entries
    # Join through AddressBook to enforce company isolation
    site_ids = db.query(Site.id).join(
        AddressBook, Site.address_book_id == AddressBook.id
    ).filter(
        Site.address_book_id.in_(accessible_ab_ids),
        AddressBook.company_id == client.company_id,  # Company isolation via join
        Site.is_active == True
    ).all()

    return [site.id for site in site_ids]


def get_client_accessible_sites(db: Session, client: ClientUser) -> List[Site]:
    """
    Get all sites accessible to a client user.
    Returns full Site objects.
    """
    site_ids = get_client_accessible_site_ids(db, client)
    if not site_ids:
        return []

    return db.query(Site).filter(Site.id.in_(site_ids)).all()


def authenticate_client(db: Session, email: str, password: str) -> Optional[ClientUser]:
    """
    Authenticate a client user by email and password.
    Returns the client user if credentials are valid, None otherwise.
    """
    client = db.query(ClientUser).filter(
        ClientUser.email == email,
        ClientUser.is_active == True
    ).first()

    if not client:
        return None

    # Check if invitation was accepted (has password set)
    if not client.hashed_password:
        return None

    if not verify_password(password, client.hashed_password):
        return None

    return client


def get_client_by_email(db: Session, email: str) -> Optional[ClientUser]:
    """Get a client user by email"""
    return db.query(ClientUser).filter(ClientUser.email == email).first()


def get_client_by_id(db: Session, client_id: int) -> Optional[ClientUser]:
    """Get a client user by ID"""
    return db.query(ClientUser).filter(ClientUser.id == client_id).first()


def get_client_by_invitation_token(db: Session, token: str) -> Optional[ClientUser]:
    """Get a client user by invitation token"""
    return db.query(ClientUser).filter(
        ClientUser.invitation_token == token,
        ClientUser.invitation_accepted_at == None  # Not yet accepted
    ).first()


def create_client_tokens(db: Session, client: ClientUser) -> dict:
    """
    Create access and refresh tokens for a client user.
    Returns dict with access_token, refresh_token, expires_in, and user.
    """
    # Create access token
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_client_access_token(client, access_token_expires)

    # Create refresh token
    refresh_token_str = generate_client_refresh_token()
    refresh_token_expiry = get_client_refresh_token_expiry()

    # Store refresh token in database
    db_refresh_token = ClientRefreshToken(
        client_user_id=client.id,
        token=refresh_token_str,
        expires_at=refresh_token_expiry
    )
    db.add(db_refresh_token)

    # Update last login
    client.last_login_at = datetime.utcnow()
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": {
            "id": client.id,
            "email": client.email,
            "name": client.name,
            "phone": client.phone,
            "company_id": client.company_id,
            "address_book_id": client.address_book_id,
            "is_active": client.is_active,
            "invitation_sent_at": client.invitation_sent_at,
            "invitation_accepted_at": client.invitation_accepted_at,
            "created_at": client.created_at,
            "last_login_at": client.last_login_at
        }
    }


def revoke_client_refresh_token(db: Session, token: str, client_id: int) -> bool:
    """Revoke a client refresh token. Returns True if found and revoked."""
    db_token = db.query(ClientRefreshToken).filter(
        ClientRefreshToken.token == token,
        ClientRefreshToken.client_user_id == client_id,
        ClientRefreshToken.is_revoked == False
    ).first()

    if db_token:
        db_token.is_revoked = True
        db_token.revoked_at = datetime.utcnow()
        db.commit()
        return True
    return False


def validate_client_refresh_token(db: Session, token: str) -> Optional[ClientUser]:
    """
    Validate a client refresh token.
    Returns the client user if valid, None otherwise.
    """
    db_token = db.query(ClientRefreshToken).filter(
        ClientRefreshToken.token == token,
        ClientRefreshToken.is_revoked == False
    ).first()

    if not db_token:
        return None

    # Check if token is expired
    if db_token.expires_at < datetime.utcnow():
        db_token.is_revoked = True
        db_token.revoked_at = datetime.utcnow()
        db.commit()
        return None

    # Get the client
    client = get_client_by_id(db, db_token.client_user_id)
    if not client or not client.is_active:
        return None

    return client
