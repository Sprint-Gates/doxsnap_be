"""
User and resource limit enforcement utilities.
"""
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models import User, Company


def check_user_limit(db: Session, company_id: int) -> dict:
    """
    Check if company has reached their user limit.

    Args:
        db: Database session
        company_id: Company ID to check

    Returns:
        dict with current_count, max_users, can_add, remaining
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not company.plan:
        # No company or no plan = no restriction
        return {
            "current_count": 0,
            "max_users": None,
            "can_add": True,
            "remaining": None
        }

    # Count only active users
    current_count = db.query(User).filter(
        User.company_id == company_id,
        User.is_active == True
    ).count()

    # Use override if set, otherwise use plan's max_users
    max_users = company.max_users_override if company.max_users_override is not None else company.plan.max_users
    can_add = current_count < max_users
    remaining = max_users - current_count

    return {
        "current_count": current_count,
        "max_users": max_users,
        "can_add": can_add,
        "remaining": remaining
    }


def enforce_user_limit(db: Session, company_id: int):
    """
    Raise HTTPException if user limit is reached.
    Call this before creating a new user.

    Args:
        db: Database session
        company_id: Company ID to check

    Raises:
        HTTPException: 403 Forbidden if user limit is reached
    """
    limit_info = check_user_limit(db, company_id)
    if not limit_info["can_add"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User limit reached ({limit_info['max_users']}). Upgrade your plan to add more users."
        )
