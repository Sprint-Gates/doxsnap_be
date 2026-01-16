"""
CRM Activities API
Handles activity tracking (calls, emails, meetings, tasks)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, and_
from typing import Optional, List
from datetime import datetime, date, time
from app.database import get_db
from app.models import CRMActivity, Lead, Opportunity, Client, User
from app.utils.security import verify_token
import logging
import json

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get the current authenticated user"""
    token = credentials.credentials
    email = verify_token(token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


# =============================================================================
# SCHEMAS
# =============================================================================

class ActivityCreate(BaseModel):
    activity_type: str  # call, email, meeting, task, note
    subject: str
    description: Optional[str] = None
    lead_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    client_id: Optional[int] = None
    due_date: Optional[datetime] = None
    due_time: Optional[str] = None  # HH:MM format
    duration_minutes: Optional[int] = None
    status: Optional[str] = "planned"
    priority: Optional[str] = "normal"
    call_direction: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[List[str]] = None
    assigned_to: Optional[int] = None
    reminder_date: Optional[datetime] = None


class ActivityUpdate(BaseModel):
    activity_type: Optional[str] = None
    subject: Optional[str] = None
    description: Optional[str] = None
    lead_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    client_id: Optional[int] = None
    due_date: Optional[datetime] = None
    due_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    outcome: Optional[str] = None
    call_direction: Optional[str] = None
    call_result: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[List[str]] = None
    assigned_to: Optional[int] = None
    reminder_date: Optional[datetime] = None


class ActivityComplete(BaseModel):
    outcome: Optional[str] = None
    call_result: Optional[str] = None  # For calls: answered, no_answer, voicemail, busy


# =============================================================================
# ENDPOINTS
# =============================================================================

def activity_to_response(act: CRMActivity, db: Session) -> dict:
    """Convert Activity model to response dict"""
    # Determine what this activity is related to
    related_to = None
    related_name = None
    if act.lead_id and act.lead:
        related_to = "lead"
        related_name = f"{act.lead.first_name} {act.lead.last_name or ''}".strip()
    elif act.opportunity_id and act.opportunity:
        related_to = "opportunity"
        related_name = act.opportunity.name
    elif act.client_id and act.client:
        related_to = "client"
        related_name = act.client.name

    attendees = None
    if act.attendees:
        try:
            attendees = json.loads(act.attendees)
        except:
            attendees = [act.attendees]

    return {
        "id": act.id,
        "activity_type": act.activity_type,
        "subject": act.subject,
        "description": act.description,
        "lead_id": act.lead_id,
        "opportunity_id": act.opportunity_id,
        "client_id": act.client_id,
        "related_to": related_to,
        "related_name": related_name,
        "due_date": act.due_date.isoformat() if act.due_date else None,
        "due_time": act.due_time.strftime("%H:%M") if act.due_time else None,
        "duration_minutes": act.duration_minutes,
        "status": act.status,
        "priority": act.priority,
        "outcome": act.outcome,
        "call_direction": act.call_direction,
        "call_result": act.call_result,
        "location": act.location,
        "attendees": attendees,
        "assigned_to": act.assigned_to,
        "assignee_name": act.assignee.name if act.assignee else None,
        "completed_by": act.completed_by,
        "completed_at": act.completed_at.isoformat() if act.completed_at else None,
        "reminder_date": act.reminder_date.isoformat() if act.reminder_date else None,
        "reminder_sent": act.reminder_sent,
        "created_by": act.created_by,
        "creator_name": act.creator.name if act.creator else None,
        "created_at": act.created_at.isoformat(),
        "updated_at": act.updated_at.isoformat() if act.updated_at else None
    }


@router.get("/crm/activities")
async def get_activities(
    activity_type: Optional[str] = None,
    status: Optional[str] = None,
    entity_type: Optional[str] = None,
    lead_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    client_id: Optional[int] = None,
    assigned_to: Optional[int] = None,
    due_from: Optional[date] = None,
    due_to: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all activities for the company"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    query = db.query(CRMActivity).filter(CRMActivity.company_id == user.company_id)

    if activity_type:
        query = query.filter(CRMActivity.activity_type == activity_type)

    if status:
        query = query.filter(CRMActivity.status == status)

    # Filter by entity type (show activities related to leads, opportunities, or clients)
    if entity_type:
        if entity_type == "lead":
            query = query.filter(CRMActivity.lead_id != None)
        elif entity_type == "opportunity":
            query = query.filter(CRMActivity.opportunity_id != None)
        elif entity_type == "client":
            query = query.filter(CRMActivity.client_id != None)

    if lead_id:
        query = query.filter(CRMActivity.lead_id == lead_id)

    if opportunity_id:
        query = query.filter(CRMActivity.opportunity_id == opportunity_id)

    if client_id:
        query = query.filter(CRMActivity.client_id == client_id)

    if assigned_to:
        query = query.filter(CRMActivity.assigned_to == assigned_to)

    if due_from:
        query = query.filter(CRMActivity.due_date >= datetime.combine(due_from, time.min))

    if due_to:
        query = query.filter(CRMActivity.due_date <= datetime.combine(due_to, time.max))

    activities = query.order_by(CRMActivity.due_date.desc().nullslast(), CRMActivity.created_at.desc()).all()

    return [activity_to_response(act, db) for act in activities]


@router.get("/crm/activities/upcoming")
async def get_upcoming_activities(
    days: int = 7,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get upcoming activities for the current user"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    from datetime import timedelta
    now = datetime.utcnow()
    end_date = now + timedelta(days=days)

    activities = db.query(CRMActivity).filter(
        CRMActivity.company_id == user.company_id,
        CRMActivity.assigned_to == user.id,
        CRMActivity.status == "planned",
        CRMActivity.due_date <= end_date
    ).order_by(CRMActivity.due_date).all()

    return [activity_to_response(act, db) for act in activities]


@router.get("/crm/activities/overdue")
async def get_overdue_activities(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get overdue activities"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    now = datetime.utcnow()

    activities = db.query(CRMActivity).filter(
        CRMActivity.company_id == user.company_id,
        CRMActivity.status == "planned",
        CRMActivity.due_date < now
    ).order_by(CRMActivity.due_date).all()

    return [activity_to_response(act, db) for act in activities]


@router.get("/crm/activities/stats")
async def get_activity_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get activity statistics"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    now = datetime.utcnow()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Count by type this month
    type_counts = db.query(
        CRMActivity.activity_type,
        func.count(CRMActivity.id)
    ).filter(
        CRMActivity.company_id == user.company_id,
        CRMActivity.created_at >= start_of_month
    ).group_by(CRMActivity.activity_type).all()

    # Count by status
    status_counts = db.query(
        CRMActivity.status,
        func.count(CRMActivity.id)
    ).filter(
        CRMActivity.company_id == user.company_id
    ).group_by(CRMActivity.status).all()

    # Overdue count
    overdue_count = db.query(CRMActivity).filter(
        CRMActivity.company_id == user.company_id,
        CRMActivity.status == "planned",
        CRMActivity.due_date < now
    ).count()

    # Due today
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    due_today = db.query(CRMActivity).filter(
        CRMActivity.company_id == user.company_id,
        CRMActivity.status == "planned",
        CRMActivity.due_date >= today_start,
        CRMActivity.due_date <= today_end
    ).count()

    # Completed this month
    completed_this_month = db.query(CRMActivity).filter(
        CRMActivity.company_id == user.company_id,
        CRMActivity.status == "completed",
        CRMActivity.completed_at >= start_of_month
    ).count()

    total = sum(c for s, c in status_counts)
    completed = next((c for s, c in status_counts if s == "completed"), 0)

    return {
        "total": total,
        "completed": completed,
        "by_type_this_month": {t: c for t, c in type_counts},
        "by_status": {s: c for s, c in status_counts},
        "overdue_count": overdue_count,
        "due_today": due_today,
        "completed_this_month": completed_this_month
    }


@router.get("/crm/activities/{activity_id}")
async def get_activity(
    activity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific activity"""
    activity = db.query(CRMActivity).filter(
        CRMActivity.id == activity_id,
        CRMActivity.company_id == user.company_id
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    return activity_to_response(activity, db)


@router.post("/crm/activities")
async def create_activity(
    data: ActivityCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new activity"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    # Validate activity type
    valid_types = ["call", "email", "meeting", "task", "note"]
    if data.activity_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Activity type must be one of: {', '.join(valid_types)}")

    # Parse due_time if provided
    due_time_obj = None
    if data.due_time:
        try:
            due_time_obj = datetime.strptime(data.due_time, "%H:%M").time()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM")

    # Serialize attendees
    attendees_json = None
    if data.attendees:
        attendees_json = json.dumps(data.attendees)

    activity = CRMActivity(
        company_id=user.company_id,
        activity_type=data.activity_type,
        subject=data.subject,
        description=data.description,
        lead_id=data.lead_id,
        opportunity_id=data.opportunity_id,
        client_id=data.client_id,
        due_date=data.due_date,
        due_time=due_time_obj,
        duration_minutes=data.duration_minutes,
        status=data.status or "planned",
        priority=data.priority or "normal",
        call_direction=data.call_direction,
        location=data.location,
        attendees=attendees_json,
        assigned_to=data.assigned_to or user.id,
        reminder_date=data.reminder_date,
        created_by=user.id
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)

    return {"id": activity.id, "message": "Activity created successfully"}


@router.put("/crm/activities/{activity_id}")
async def update_activity(
    activity_id: int,
    data: ActivityUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an activity"""
    activity = db.query(CRMActivity).filter(
        CRMActivity.id == activity_id,
        CRMActivity.company_id == user.company_id
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    update_data = data.dict(exclude_unset=True)

    # Handle due_time specially
    if "due_time" in update_data:
        if update_data["due_time"]:
            try:
                update_data["due_time"] = datetime.strptime(update_data["due_time"], "%H:%M").time()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM")
        else:
            update_data["due_time"] = None

    # Handle attendees specially
    if "attendees" in update_data:
        if update_data["attendees"]:
            update_data["attendees"] = json.dumps(update_data["attendees"])
        else:
            update_data["attendees"] = None

    for field, value in update_data.items():
        setattr(activity, field, value)

    db.commit()
    return {"message": "Activity updated successfully"}


@router.post("/crm/activities/{activity_id}/complete")
async def complete_activity(
    activity_id: int,
    data: ActivityComplete,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark an activity as completed"""
    activity = db.query(CRMActivity).filter(
        CRMActivity.id == activity_id,
        CRMActivity.company_id == user.company_id
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    activity.status = "completed"
    activity.completed_at = datetime.utcnow()
    activity.completed_by = user.id

    if data.outcome:
        activity.outcome = data.outcome

    if data.call_result and activity.activity_type == "call":
        activity.call_result = data.call_result

    db.commit()
    return {"message": "Activity marked as completed"}


@router.post("/crm/activities/{activity_id}/cancel")
async def cancel_activity(
    activity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel an activity"""
    activity = db.query(CRMActivity).filter(
        CRMActivity.id == activity_id,
        CRMActivity.company_id == user.company_id
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    activity.status = "cancelled"
    db.commit()
    return {"message": "Activity cancelled"}


@router.delete("/crm/activities/{activity_id}")
async def delete_activity(
    activity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an activity"""
    activity = db.query(CRMActivity).filter(
        CRMActivity.id == activity_id,
        CRMActivity.company_id == user.company_id
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    db.delete(activity)
    db.commit()
    return {"message": "Activity deleted successfully"}


# =============================================================================
# TIMELINE ENDPOINT
# =============================================================================

@router.get("/crm/timeline/{entity_type}/{entity_id}")
async def get_entity_timeline(
    entity_type: str,
    entity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get activity timeline for a lead, opportunity, or client"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    if entity_type not in ["lead", "opportunity", "client"]:
        raise HTTPException(status_code=400, detail="Entity type must be lead, opportunity, or client")

    query = db.query(CRMActivity).filter(CRMActivity.company_id == user.company_id)

    if entity_type == "lead":
        query = query.filter(CRMActivity.lead_id == entity_id)
    elif entity_type == "opportunity":
        query = query.filter(CRMActivity.opportunity_id == entity_id)
    else:
        query = query.filter(CRMActivity.client_id == entity_id)

    activities = query.order_by(CRMActivity.created_at.desc()).all()

    return [activity_to_response(act, db) for act in activities]
