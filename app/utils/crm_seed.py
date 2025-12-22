"""
CRM Seed Utility

Automatically populates default CRM data for a new company:
- Lead Sources
- Pipeline Stages
"""

from sqlalchemy.orm import Session
import logging

from app.models import LeadSource, PipelineStage

logger = logging.getLogger(__name__)


# =============================================================================
# DEFAULT LEAD SOURCES
# =============================================================================

DEFAULT_LEAD_SOURCES = [
    {"code": "WEB", "name": "Website", "description": "Leads from website contact forms", "sort_order": 1},
    {"code": "REF", "name": "Referral", "description": "Customer or partner referrals", "sort_order": 2},
    {"code": "CALL", "name": "Cold Call", "description": "Outbound cold calling", "sort_order": 3},
    {"code": "EMAIL", "name": "Email Campaign", "description": "Email marketing campaigns", "sort_order": 4},
    {"code": "TRADE", "name": "Trade Show", "description": "Trade shows and events", "sort_order": 5},
    {"code": "SOCIAL", "name": "Social Media", "description": "LinkedIn, Facebook, etc.", "sort_order": 6},
    {"code": "AD", "name": "Advertisement", "description": "Paid advertising", "sort_order": 7},
    {"code": "OTHER", "name": "Other", "description": "Other lead sources", "sort_order": 99},
]


# =============================================================================
# DEFAULT PIPELINE STAGES
# =============================================================================

DEFAULT_PIPELINE_STAGES = [
    {"code": "NEW", "name": "New", "color": "#6366f1", "probability": 10, "is_won": False, "is_lost": False, "sort_order": 1},
    {"code": "QUAL", "name": "Qualified", "color": "#8b5cf6", "probability": 25, "is_won": False, "is_lost": False, "sort_order": 2},
    {"code": "PROP", "name": "Proposal", "color": "#a855f7", "probability": 50, "is_won": False, "is_lost": False, "sort_order": 3},
    {"code": "NEG", "name": "Negotiation", "color": "#d946ef", "probability": 75, "is_won": False, "is_lost": False, "sort_order": 4},
    {"code": "WON", "name": "Won", "color": "#22c55e", "probability": 100, "is_won": True, "is_lost": False, "sort_order": 5},
    {"code": "LOST", "name": "Lost", "color": "#ef4444", "probability": 0, "is_won": False, "is_lost": True, "sort_order": 6},
]


def seed_lead_sources(company_id: int, db: Session) -> dict:
    """
    Create default lead sources for a company.

    Returns:
        dict with statistics about what was created
    """
    stats = {
        "created": 0,
        "skipped": 0
    }

    for source_data in DEFAULT_LEAD_SOURCES:
        existing = db.query(LeadSource).filter(
            LeadSource.company_id == company_id,
            LeadSource.code == source_data["code"]
        ).first()

        if existing:
            stats["skipped"] += 1
            continue

        source = LeadSource(
            company_id=company_id,
            code=source_data["code"],
            name=source_data["name"],
            description=source_data["description"],
            sort_order=source_data["sort_order"],
            is_active=True
        )
        db.add(source)
        stats["created"] += 1

    return stats


def seed_pipeline_stages(company_id: int, db: Session) -> dict:
    """
    Create default pipeline stages for a company.

    Returns:
        dict with statistics about what was created
    """
    stats = {
        "created": 0,
        "skipped": 0
    }

    for stage_data in DEFAULT_PIPELINE_STAGES:
        existing = db.query(PipelineStage).filter(
            PipelineStage.company_id == company_id,
            PipelineStage.code == stage_data["code"]
        ).first()

        if existing:
            stats["skipped"] += 1
            continue

        stage = PipelineStage(
            company_id=company_id,
            code=stage_data["code"],
            name=stage_data["name"],
            color=stage_data["color"],
            probability=stage_data["probability"],
            is_won=stage_data["is_won"],
            is_lost=stage_data["is_lost"],
            sort_order=stage_data["sort_order"],
            is_active=True
        )
        db.add(stage)
        stats["created"] += 1

    return stats


def seed_crm_defaults(company_id: int, db: Session) -> dict:
    """
    Seed all default CRM data for a new company.

    This includes:
    - Lead Sources
    - Pipeline Stages

    Args:
        company_id: The company ID to seed data for
        db: Database session

    Returns:
        dict with statistics about what was created
    """
    logger.info(f"Seeding CRM defaults for company {company_id}")

    results = {
        "lead_sources": None,
        "pipeline_stages": None,
        "errors": []
    }

    try:
        # Seed Lead Sources
        source_stats = seed_lead_sources(company_id, db)
        results["lead_sources"] = source_stats
        logger.info(f"Lead sources seeded for company {company_id}: {source_stats}")
    except Exception as e:
        logger.error(f"Error seeding lead sources for company {company_id}: {e}")
        results["errors"].append(f"Lead sources: {str(e)}")

    try:
        # Seed Pipeline Stages
        stage_stats = seed_pipeline_stages(company_id, db)
        results["pipeline_stages"] = stage_stats
        logger.info(f"Pipeline stages seeded for company {company_id}: {stage_stats}")
    except Exception as e:
        logger.error(f"Error seeding pipeline stages for company {company_id}: {e}")
        results["errors"].append(f"Pipeline stages: {str(e)}")

    return results
