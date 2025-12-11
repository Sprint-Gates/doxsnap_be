from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
from datetime import datetime

from app.database import get_db
from app.models import Branch, Client, Floor, Room, Equipment, SubEquipment, Company, User

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


@router.post("/dummy/flush-assets")
def flush_assets(db: Session = Depends(get_db)):
    """Flush all assets (SubEquipment, Equipment, Room, Floor) - DANGEROUS!"""
    try:
        # Delete in order due to foreign keys
        sub_count = db.query(SubEquipment).delete()
        equip_count = db.query(Equipment).delete()
        room_count = db.query(Room).delete()
        floor_count = db.query(Floor).delete()
        db.commit()

        return {
            "message": "Assets flushed successfully",
            "deleted": {
                "sub_equipment": sub_count,
                "equipment": equip_count,
                "rooms": room_count,
                "floors": floor_count
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dummy/import-assets-step1")
def import_assets_step1(db: Session = Depends(get_db)):
    """Step 1: Create floors, rooms, and main equipment from JSON"""
    import json
    json_path = os.path.join(os.path.dirname(__file__), "..", "..", "misc", "assets-import.json")

    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail=f"JSON file not found: {json_path}")

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)

        # Build branch code to ID mapping
        branches = db.query(Branch).all()
        branch_map = {b.code: b.id for b in branches if b.code}

        # Track created entities
        created_floors = {}
        created_rooms = {}

        stats = {
            "floors_created": 0,
            "rooms_created": 0,
            "equipment_created": 0,
            "skipped_no_branch": 0
        }

        # Get unique branch codes from main equipment
        branch_codes_with_assets = set(item['branch_code'] for item in data['main_equipment'])

        # Create floors and rooms
        for branch_code_str in branch_codes_with_assets:
            if branch_code_str in branch_map:
                branch_id = branch_map[branch_code_str]

                if branch_id not in created_floors:
                    floor = Floor(
                        branch_id=branch_id,
                        name="Default Floor",
                        code="DF",
                        level=0
                    )
                    db.add(floor)
                    db.flush()
                    created_floors[branch_id] = floor.id
                    stats["floors_created"] += 1

                    room = Room(
                        floor_id=floor.id,
                        name="Default Room",
                        code="DR",
                        room_type="General"
                    )
                    db.add(room)
                    db.flush()
                    created_rooms[branch_id] = room.id
                    stats["rooms_created"] += 1

        # Import main equipment
        for item in data['main_equipment']:
            branch_code_str = item['branch_code']
            if branch_code_str not in branch_map:
                stats["skipped_no_branch"] += 1
                continue

            branch_id = branch_map[branch_code_str]
            room_id = created_rooms.get(branch_id)
            if not room_id:
                stats["skipped_no_branch"] += 1
                continue

            install_date = None
            if item.get('date_acquired'):
                try:
                    install_date = pd.to_datetime(item['date_acquired'], format='%d/%m/%y').date()
                except:
                    pass

            equipment = Equipment(
                room_id=room_id,
                name=item['name'],
                code=str(item['asset_number']),
                category=item['category'],
                manufacturer=item.get('manufacturer'),
                serial_number=item.get('serial_number'),
                installation_date=install_date
            )
            db.add(equipment)
            stats["equipment_created"] += 1

        db.commit()
        return {"message": "Step 1 completed", "stats": stats}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dummy/import-assets-step2")
def import_assets_step2(batch: int = 0, batch_size: int = 10000, db: Session = Depends(get_db)):
    """Step 2: Import sub-equipment in batches from JSON."""
    import json
    json_path = os.path.join(os.path.dirname(__file__), "..", "..", "misc", "assets-import.json")

    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail=f"JSON file not found: {json_path}")

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)

        # Build equipment code to ID mapping from database
        equipment_list = db.query(Equipment).all()
        equipment_map = {int(e.code): e.id for e in equipment_list if e.code and e.code.isdigit()}

        sub_equipment_list = data['sub_equipment']
        total_rows = len(sub_equipment_list)

        start_idx = batch * batch_size
        end_idx = min(start_idx + batch_size, total_rows)

        if start_idx >= total_rows:
            return {"message": "All batches completed", "total_rows": total_rows}

        batch_items = sub_equipment_list[start_idx:end_idx]

        stats = {
            "batch": batch,
            "start_idx": start_idx,
            "end_idx": end_idx,
            "total_rows": total_rows,
            "sub_equipment_created": 0,
            "skipped_no_parent": 0
        }

        for item in batch_items:
            parent_num = item.get('parent_number')
            if parent_num is None or parent_num not in equipment_map:
                stats["skipped_no_parent"] += 1
                continue

            equipment_id = equipment_map[parent_num]

            sub_equip = SubEquipment(
                equipment_id=equipment_id,
                name=item['name'],
                code=str(item['asset_number']),
                component_type=item.get('component_type'),
                manufacturer=item.get('manufacturer'),
                serial_number=item.get('serial_number')
            )
            db.add(sub_equip)
            stats["sub_equipment_created"] += 1

        db.commit()

        remaining_batches = (total_rows - end_idx + batch_size - 1) // batch_size
        return {
            "message": f"Batch {batch} completed",
            "stats": stats,
            "remaining_batches": remaining_batches,
            "next_batch": batch + 1 if end_idx < total_rows else None
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/dummy/user-role")
def update_user_role(
    email: str,
    role: str,
    db: Session = Depends(get_db)
):
    """Update a user's role - for admin use only"""
    valid_roles = ["admin", "operator", "accounting"]
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User with email {email} not found")

    old_role = user.role
    user.role = role
    db.commit()

    return {
        "email": email,
        "old_role": old_role,
        "new_role": role,
        "message": "Role updated successfully. Please log out and log in again."
    }