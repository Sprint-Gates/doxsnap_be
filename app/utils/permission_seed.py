"""
Permissions Seed Utility

Automatically populates the permissions table from a static
(module, action) dictionary.

Permissions are global system vocabulary and are NOT company-specific.
Admins can later assign these permissions to roles.
"""

import logging
from sqlalchemy.orm import Session

from app.models import Permission

logger = logging.getLogger(__name__)

# =============================================================================
# PERMISSIONS DICTIONARY
# =============================================================================
# Single source of truth for all system permissions.
# DO NOT rename existing module/action pairs once deployed.
# Add new permissions instead.
# =============================================================================

PERMISSIONS_DICTIONARY = {
    "users": {
        "view": "View users",
        "create": "Create users",
        "update": "Edit users",
        "delete": "Delete users",
    },
    "roles": {
        "view": "View roles",
        "manage": "Create and edit roles",
    },
    "warehouses": {
        "view": "View warehouses",
        "assign": "Assign warehouses to users",
    },
    "branches": {
        "view": "View branches",
        "assign": "Assign branches to users",
    },
    "companies": {
        "view": "View company settings",
        "update": "Update company settings",
    },
}

# =============================================================================
# SEED FUNCTION
# =============================================================================

def seed_permissions(db: Session):
    """
    Seed permissions from PERMISSIONS_DICTIONARY.

    This function is idempotent:
    - Existing permissions are not modified
    - Missing permissions are created
    - No permissions are deleted

    Args:
        db: SQLAlchemy database session
    """
    logger.info("Seeding permissions...")

    try:
        for module, actions in PERMISSIONS_DICTIONARY.items():
            for action in actions.keys():
                exists = (
                    db.query(Permission)
                    .filter_by(module=module, action=action)
                    .first()
                )
                if exists:
                    continue

                db.add(Permission(module=module, action=action))

        db.commit()
        logger.info("Permissions seeding completed successfully.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding permissions: {e}")
        raise
