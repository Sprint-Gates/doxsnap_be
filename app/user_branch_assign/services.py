"""
Business logic for UserBranchAssignment (UBA) services
"""

import logging
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from uuid import UUID

from app.models import UserBranchAssignment, User, Branch
from app.user_branch_assign.schema import UserBranchAssignmentCreateRequest

# Configure logger
logger = logging.getLogger(__name__)


def assign_user_to_branch(db: Session,user_id:str, branch_id:str, data: UserBranchAssignmentCreateRequest) -> JSONResponse:
    """
    Assign a user to a branch.
    """
    try:
        branch_uuid = UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch ID. Must be a valid UUID.")
    

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID. Must be a valid UUID.")

    user = db.query(User).filter(User.user_id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    branch = db.query(Branch).filter(Branch.branch_id == branch_uuid).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    # Check if assignment already exists
    existing = db.query(UserBranchAssignment).filter(
        UserBranchAssignment.uba_user_id == user_uuid,
        UserBranchAssignment.uba_branch_id == branch_uuid
    ).first()

    if existing:
        if existing.uba_is_active:
            raise HTTPException(status_code=409, detail="User is already assigned to this branch")
        else:
            # Reactivate inactive assignment
            existing.uba_is_active = True
            db.commit()
            db.refresh(existing)
            return JSONResponse(
                content={
                    "uba_id": str(existing.uba_id),
                    "uba_user_id": str(existing.uba_user_id),
                    "uba_branch_id": str(existing.uba_branch_id),
                    "uba_is_active": existing.uba_is_active,
                    "message": "User-branch assignment reactivated"
                },
                status_code=200
            )

    try:
        assignment = UserBranchAssignment(
            uba_user_id=user_uuid,
            uba_branch_id=branch_uuid,
            uba_is_active=data.uba_is_active
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
    except Exception as exc:
        db.rollback()
        logger.error("UBA creation failed", extra={"error": str(exc), "user_id": user_uuid, "branch_id": branch_uuid})
        raise HTTPException(status_code=500, detail="Failed to assign user to branch")

    return JSONResponse(
        content={
            "uba_id": str(assignment.uba_id),
            "uba_user_id": str(assignment.uba_user_id),
            "uba_branch_id": str(assignment.uba_branch_id),
            "uba_is_active": assignment.uba_is_active,
            "message": "User assigned to branch successfully"
        },
        status_code=201
    )


def update_assignment_status(db: Session, uba_id: str, is_active: bool) -> JSONResponse:
    """
    Update the active status of a user-branch assignment.
    """
    try:
        assignment_uuid = UUID(uba_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid assignment ID. Must be a valid UUID.")

    assignment = db.query(UserBranchAssignment).filter(UserBranchAssignment.uba_id == assignment_uuid).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    try:
        assignment.uba_is_active = is_active
        db.commit()
        db.refresh(assignment)
    except Exception as exc:
        db.rollback()
        logger.error("UBA update failed", extra={"error": str(exc), "uba_id": assignment_uuid})
        raise HTTPException(status_code=500, detail="Failed to update assignment status")

    return JSONResponse(
        content={
            "uba_id": str(assignment.uba_id),
            "uba_user_id": str(assignment.uba_user_id),
            "uba_branch_id": str(assignment.uba_branch_id),
            "uba_is_active": assignment.uba_is_active,
            "message": "Assignment status updated successfully"
        },
        status_code=200
    )


def disable_assignment(db: Session, uba_id: str) -> JSONResponse:
    """
    Disable a user-branch assignment (soft delete).
    """
    return update_assignment_status(db, uba_id, is_active=False)


def list_assignments_by_user(db: Session, user_id: str) -> list[dict]:
    """
    List all branch assignments for a user.
    """
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID. Must be a valid UUID.")

    assignments = db.query(UserBranchAssignment).filter(UserBranchAssignment.uba_user_id == user_uuid).all()
    return [
        {
            "uba_id": str(a.uba_id),
            "uba_user_id": str(a.uba_user_id),
            "uba_branch_id": str(a.uba_branch_id),
            "uba_is_active": a.uba_is_active
        } for a in assignments
    ]


def list_assignments_by_branch(db: Session, branch_id: str) -> list[dict]:
    """
    List all user assignments for a branch.
    """
    try:
        branch_uuid = UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch ID. Must be a valid UUID.")

    assignments = db.query(UserBranchAssignment).filter(UserBranchAssignment.uba_branch_id == branch_uuid).all()
    return [
        {
            "uba_id": str(a.uba_id),
            "uba_user_id": str(a.uba_user_id),
            "uba_branch_id": str(a.uba_branch_id),
            "uba_is_active": a.uba_is_active
        } for a in assignments
    ]
