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


@router.post("/dummy/import-assets")
def import_assets(db: Session = Depends(get_db)):
    """Import assets from Excel file"""
    excel_path = os.path.join(os.path.dirname(__file__), "..", "..", "misc", "assets-mmg.xlsx")

    if not os.path.exists(excel_path):
        raise HTTPException(status_code=404, detail=f"Excel file not found: {excel_path}")

    try:
        df = pd.read_excel(excel_path)

        # Build branch code to ID mapping
        branches = db.query(Branch).all()
        branch_map = {b.code: b.id for b in branches if b.code}

        # Track created entities
        created_floors = {}  # branch_id -> floor_id
        created_rooms = {}   # branch_id -> room_id
        created_equipment = {}  # asset_number -> equipment_id

        stats = {
            "floors_created": 0,
            "rooms_created": 0,
            "equipment_created": 0,
            "sub_equipment_created": 0,
            "skipped_no_branch": 0,
            "skipped_no_parent": 0
        }

        # First pass: Create floors and rooms for branches that have assets
        branch_codes_with_assets = df['Address Number'].dropna().unique()
        for branch_code in branch_codes_with_assets:
            branch_code_str = str(int(branch_code))
            if branch_code_str in branch_map:
                branch_id = branch_map[branch_code_str]

                # Create default floor if not exists
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

                    # Create default room
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

        # Second pass: Import main equipment (Asset Number = Parent Number)
        main_equipment = df[df['Asset Number'] == df['Parent Number']]
        for _, row in main_equipment.iterrows():
            address_num = row.get('Address Number')
            if pd.isna(address_num):
                stats["skipped_no_branch"] += 1
                continue

            branch_code_str = str(int(address_num))
            if branch_code_str not in branch_map:
                stats["skipped_no_branch"] += 1
                continue

            branch_id = branch_map[branch_code_str]
            room_id = created_rooms.get(branch_id)
            if not room_id:
                stats["skipped_no_branch"] += 1
                continue

            # Parse date
            install_date = None
            date_str = row.get('Date Acquired')
            if pd.notna(date_str):
                try:
                    install_date = pd.to_datetime(date_str, format='%d/%m/%y').date()
                except:
                    pass

            warranty_date = None
            warranty_str = row.get('Warranty Expiration')
            if pd.notna(warranty_str):
                try:
                    warranty_date = pd.to_datetime(warranty_str, format='%d/%m/%y').date()
                except:
                    pass

            equipment = Equipment(
                room_id=room_id,
                name=str(row.get('Description ', 'Unknown')).strip()[:255],
                code=str(int(row['Asset Number'])),
                category=str(row.get('Description .1', 'General')).strip()[:100] if pd.notna(row.get('Description .1')) else 'General',
                equipment_type=str(row.get('Eqm Cls', '')).strip()[:50] if pd.notna(row.get('Eqm Cls')) else None,
                manufacturer=str(row.get('Mfg ', '')).strip()[:100] if pd.notna(row.get('Mfg ')) else None,
                serial_number=str(row.get('Serial Number', '')).strip()[:100] if pd.notna(row.get('Serial Number')) else None,
                installation_date=install_date,
                warranty_expiry=warranty_date
            )
            db.add(equipment)
            db.flush()
            created_equipment[int(row['Asset Number'])] = equipment.id
            stats["equipment_created"] += 1

        # Third pass: Import sub-equipment
        sub_equipment_df = df[df['Asset Number'] != df['Parent Number']]
        for _, row in sub_equipment_df.iterrows():
            parent_num = int(row['Parent Number']) if pd.notna(row['Parent Number']) else None
            if parent_num is None or parent_num not in created_equipment:
                stats["skipped_no_parent"] += 1
                continue

            equipment_id = created_equipment[parent_num]

            # Parse dates
            install_date = None
            date_str = row.get('Date Acquired')
            if pd.notna(date_str):
                try:
                    install_date = pd.to_datetime(date_str, format='%d/%m/%y').date()
                except:
                    pass

            warranty_date = None
            warranty_str = row.get('Warranty Expiration')
            if pd.notna(warranty_str):
                try:
                    warranty_date = pd.to_datetime(warranty_str, format='%d/%m/%y').date()
                except:
                    pass

            sub_equip = SubEquipment(
                equipment_id=equipment_id,
                name=str(row.get('Description ', 'Unknown')).strip()[:255],
                code=str(int(row['Asset Number'])),
                component_type=str(row.get('Description .1', '')).strip()[:100] if pd.notna(row.get('Description .1')) else None,
                manufacturer=str(row.get('Mfg ', '')).strip()[:100] if pd.notna(row.get('Mfg ')) else None,
                serial_number=str(row.get('Serial Number', '')).strip()[:100] if pd.notna(row.get('Serial Number')) else None,
                installation_date=install_date,
                warranty_expiry=warranty_date
            )
            db.add(sub_equip)
            stats["sub_equipment_created"] += 1

            # Commit in batches to avoid memory issues
            if stats["sub_equipment_created"] % 1000 == 0:
                db.flush()

        db.commit()

        return {
            "message": "Assets imported successfully",
            "stats": stats
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))