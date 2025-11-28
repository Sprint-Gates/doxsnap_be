from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.user_branch_assign.schema import (
    UserBranchAssignmentCreateRequest,
    UserBranchAssignmentResponse
)
from app.user_branch_assign.services import (
    assign_user_to_branch,
    update_assignment_status,
    disable_assignment,
    list_assignments_by_user,
    list_assignments_by_branch
)

router = APIRouter(
    prefix="/api",
    tags=["UserBranchAssignment"]
)


@router.post(
    "/branches/assign",
    response_model=UserBranchAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign User to Branch",
    description="Assign a user to a branch or reactivate an inactive assignment."
)
def create_uba(
    user_id:str,
    branch_id:str,
    data: UserBranchAssignmentCreateRequest,
    db: Session = Depends(get_db)
):
    try:
        return assign_user_to_branch(db,user_id, branch_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to assign user to branch: {str(e)}"
        )


@router.put(
    "/branches/assign/{uba_id}",
    response_model=UserBranchAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Assignment Status",
    description="Activate or deactivate a user-branch assignment."
)
def edit_uba_status(
    uba_id: str,
    is_active: bool,
    db: Session = Depends(get_db)
):
    try:
        return update_assignment_status(db, uba_id, is_active)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update assignment status: {str(e)}"
        )


@router.delete(
    "/branches/assign/{uba_id}",
    status_code=status.HTTP_200_OK,
    summary="Disable Assignment",
    description="Disable a user-branch assignment (soft delete)."
)
def remove_uba(
    uba_id: str,
    db: Session = Depends(get_db)
):
    try:
        return disable_assignment(db, uba_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disable assignment: {str(e)}"
        )


@router.get(
    "/users/{user_id}/assignments",
    status_code=status.HTTP_200_OK,
    summary="List Branch Assignments for User",
    description="Get all branch assignments for a given user."
)
def get_assignments_by_user(
    user_id: str,
    db: Session = Depends(get_db)
):
    try:
        return list_assignments_by_user(db, user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch assignments for user: {str(e)}"
        )


@router.get(
    "/branches/{branch_id}/assignments",
    status_code=status.HTTP_200_OK,
    summary="List User Assignments for Branch",
    description="Get all users assigned to a given branch."
)
def get_assignments_by_branch(
    branch_id: str,
    db: Session = Depends(get_db)
):
    try:
        return list_assignments_by_branch(db, branch_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch assignments for branch: {str(e)}"
        )
