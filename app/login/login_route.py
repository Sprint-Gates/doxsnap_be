from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.login.schema import LoginRequest, LoginResponse
from app.login.services import login_user

router = APIRouter(
prefix="/auth",
tags=["auth"]
)

@router.post(
"/login",
response_model=LoginResponse,
status_code=status.HTTP_200_OK,
summary="User login",
description="Authenticate user and return access and refresh tokens."
)
def login(
request: Request,
data: LoginRequest,
db: Session = Depends(get_db)
):
    """
    Handle user login request.

    Steps:
    1. Retrieve user and auth record from database
    2. Check if account is locked due to failed login attempts
    3. Verify password
    4. Issue access and refresh tokens
    5. Return tokens in response body

    Args:
        request: FastAPI request object (to get client IP)
        data: LoginRequest containing email and password
        db: Database session

    Returns:
        LoginResponse: Access and refresh tokens

    Raises:
        HTTPException 401: Invalid credentials or incorrect password
        HTTPException 403: Account temporarily locked due to failed login attempts
        HTTPException 500: Unexpected error during login
    """
    ip_address = request.client.host

    try:
        tokens = login_user(db, data, ip_address)
        return tokens
    except HTTPException:
        # Propagate HTTPExceptions raised by service
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )