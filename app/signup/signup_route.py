from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.signup.schema import SignupRequest, SignupResponse
from app.signup.services import signup_user

router = APIRouter(
prefix="/auth",
tags=["auth"]
)

@router.post(
"/signup",
response_model=SignupResponse,
status_code=status.HTTP_201_CREATED,
summary="User signup",
description="Register a new user and issue access and refresh tokens. Sets HttpOnly refresh token cookie."
)
def signup(
request: Request,
data: SignupRequest,
db: Session = Depends(get_db)
):
    """
    Handle user signup request.
    
    Steps:
    1. Check if email is already registered
    2. Validate password complexity
    3. Create user record and authentication record
    4. Issue access and refresh tokens
    5. Return access token and set refresh token in HttpOnly cookie

    Args:
        request: FastAPI request object (to get client IP)
        data: SignupRequest containing email, password, username, and optional avatar
        db: Database session

    Returns:
        SignupResponse: Access and refresh tokens along with user info

    Raises:
        HTTPException 400: Email already exists or invalid password
        HTTPException 500: Unexpected error during signup
    """
    ip_address = request.client.host

    try:
        result = signup_user(db, data, ip_address)
        return result
    except HTTPException:
        # Propagate HTTPExceptions raised by service
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Signup failed: {str(e)}"
        )