from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import Branch, Client

router = APIRouter()


class BranchCreateNoLimit(BaseModel):
    client_id: int
    name: str
    code: Optional[str] = None


@router.get("/dummy")
def test():
    return "test"


@router.post("/dummy/add-branch")
def add_branch_no_limit(
    data: BranchCreateNoLimit,
    db: Session = Depends(get_db)
):
    """Add a branch without plan limits - for admin use only"""
    # Verify client exists
    client = db.query(Client).filter(Client.id == data.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Check if branch with same code already exists
    if data.code:
        existing = db.query(Branch).filter(Branch.code == data.code).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Branch with code {data.code} already exists")

    branch = Branch(
        client_id=data.client_id,
        name=data.name,
        code=data.code
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)

    return {
        "id": branch.id,
        "client_id": branch.client_id,
        "name": branch.name,
        "code": branch.code,
        "message": "Branch created successfully"
    }