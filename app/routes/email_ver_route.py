from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import EmailVerification, User

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    verification = db.query(EmailVerification).filter(EmailVerification.emvr_token == token).first()

    if not verification:
        raise HTTPException(status_code=400, detail="Invalid verification token.")

    if verification.emvr_expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Verification token expired.")

    # Update user as verified
    user = db.query(User).filter(User.user_id == verification.emvr_user_id).first()
    user.user_is_verified = True
    db.commit()

    # Optional: delete the token after verification
    db.delete(verification)
    db.commit()

    return {"message": "Email verified successfully!"}
