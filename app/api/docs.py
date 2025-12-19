from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
from typing import List
import os
import re

router = APIRouter()

# Path to documentation files
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "docs")

# Documentation metadata
DOCS_METADATA = {
    "condition-report-guide": {
        "title": "Condition Reports",
        "description": "Document and track facility issues from site inspections",
        "icon": "clipboard-list",
        "category": "Operations"
    },
    "cycle-count-guide": {
        "title": "Cycle Counts",
        "description": "Physical inventory verification and adjustments",
        "icon": "calculator",
        "category": "Inventory"
    },
    "nps-guide": {
        "title": "NPS Surveys",
        "description": "Measure and track client satisfaction with Net Promoter Score",
        "icon": "thumbs-up",
        "category": "Management"
    },
    "petty-cash-guide": {
        "title": "Petty Cash",
        "description": "Manage technician petty cash funds and expenses",
        "icon": "wallet",
        "category": "Procurement"
    },
    "slow-moving-items-guide": {
        "title": "Slow Moving Items",
        "description": "Identify and manage slow-moving and non-moving inventory",
        "icon": "clock",
        "category": "Inventory"
    },
    "technician-evaluation-guide": {
        "title": "Technician Evaluations",
        "description": "Conduct and track technician performance reviews",
        "icon": "user-check",
        "category": "HR"
    }
}


@router.get("/")
async def list_documentation():
    """List all available documentation files with metadata"""
    docs = []

    for slug, meta in DOCS_METADATA.items():
        file_path = os.path.join(DOCS_DIR, f"{slug}.md")
        if os.path.exists(file_path):
            docs.append({
                "slug": slug,
                "title": meta["title"],
                "description": meta["description"],
                "icon": meta["icon"],
                "category": meta["category"]
            })

    # Sort by category then title
    docs.sort(key=lambda x: (x["category"], x["title"]))

    return {"docs": docs}


@router.get("/{slug}", response_class=PlainTextResponse)
async def get_documentation(slug: str):
    """Get documentation content by slug"""
    # Sanitize slug to prevent directory traversal
    slug = re.sub(r'[^a-zA-Z0-9\-]', '', slug)

    file_path = os.path.join(DOCS_DIR, f"{slug}.md")

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documentation not found"
        )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error reading documentation"
        )


@router.get("/search/{query}")
async def search_documentation(query: str):
    """Search across all documentation files"""
    results = []
    query_lower = query.lower()

    for slug, meta in DOCS_METADATA.items():
        file_path = os.path.join(DOCS_DIR, f"{slug}.md")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Search in content
                content_lower = content.lower()
                if query_lower in content_lower:
                    # Find matching lines for context
                    matches = []
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if query_lower in line.lower():
                            # Get context (line and surrounding)
                            context = line.strip()
                            if len(context) > 150:
                                # Find the query position and show context around it
                                pos = context.lower().find(query_lower)
                                start = max(0, pos - 50)
                                end = min(len(context), pos + len(query) + 100)
                                context = ("..." if start > 0 else "") + context[start:end] + ("..." if end < len(context) else "")
                            matches.append({
                                "line": i + 1,
                                "text": context
                            })
                            if len(matches) >= 3:  # Limit matches per doc
                                break

                    if matches:
                        results.append({
                            "slug": slug,
                            "title": meta["title"],
                            "category": meta["category"],
                            "matches": matches
                        })
            except:
                pass

    return {"query": query, "results": results}
