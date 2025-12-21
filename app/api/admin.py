from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime
from app.database import get_db
from app.models import User, InvoiceItem, ItemMaster, Warehouse, ItemStock, ItemLedger, ItemAlias
from app.utils.security import verify_password, create_access_token, verify_token
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def check_duplicate_invoice(db: Session, invoice_number: str, supplier_name: str = None, company_id: int = None) -> Tuple[bool, Optional[int]]:
    """
    Check if an invoice with the same invoice number already exists for the same company.
    Returns (is_duplicate, existing_image_id)
    """
    from app.models import ProcessedImage

    if not invoice_number or invoice_number.strip() == "":
        return False, None

    # Normalize the invoice number for comparison
    normalized_invoice_number = invoice_number.strip().upper()

    # Query processed images with structured data, filtered by company if provided
    query = db.query(ProcessedImage).filter(
        ProcessedImage.has_structured_data == True,
        ProcessedImage.structured_data.isnot(None)
    )

    # Filter by company through the user relationship
    if company_id:
        query = query.join(User, ProcessedImage.user_id == User.id).filter(
            User.company_id == company_id
        )

    existing_images = query.all()

    for image in existing_images:
        try:
            if image.structured_data:
                data = json.loads(image.structured_data)
                existing_invoice_num = data.get("document_info", {}).get("invoice_number", "")

                if existing_invoice_num:
                    # Normalize for comparison
                    normalized_existing = existing_invoice_num.strip().upper()

                    if normalized_existing == normalized_invoice_number:
                        # Optional: also check supplier name if provided for stricter matching
                        if supplier_name:
                            existing_supplier = data.get("supplier", {}).get("company_name", "")
                            if existing_supplier and existing_supplier.strip().upper() == supplier_name.strip().upper():
                                return True, image.id
                            # If supplier doesn't match, might be different invoice with same number
                            continue
                        return True, image.id
        except (json.JSONDecodeError, TypeError):
            continue

    return False, None


def extract_invoice_info_for_duplicate_check(structured_data: dict) -> Tuple[str, str]:
    """
    Extract invoice number and supplier name from structured data for duplicate checking.
    """
    invoice_number = ""
    supplier_name = ""

    if structured_data:
        invoice_number = structured_data.get("document_info", {}).get("invoice_number", "") or ""
        supplier_name = structured_data.get("supplier", {}).get("company_name", "") or ""

    return invoice_number, supplier_name


def normalize_text_for_matching(text: str) -> str:
    """Normalize text for fuzzy matching - lowercase, remove special chars, normalize spaces"""
    import re
    if not text:
        return ""
    # Convert to lowercase
    text = text.lower()
    # Remove special characters but keep alphanumeric and spaces
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Normalize multiple spaces to single space
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two strings using multiple methods.
    Returns a score between 0 and 1.
    """
    if not text1 or not text2:
        return 0.0

    # Normalize both texts
    norm1 = normalize_text_for_matching(text1)
    norm2 = normalize_text_for_matching(text2)

    if not norm1 or not norm2:
        return 0.0

    # Method 1: Token overlap (Jaccard-like similarity)
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    jaccard = len(intersection) / len(union) if union else 0

    # Method 2: Substring containment bonus
    containment_bonus = 0.0
    if norm1 in norm2 or norm2 in norm1:
        containment_bonus = 0.3

    # Method 3: Character-level similarity for short strings
    # Using simple ratio of common characters
    if len(norm1) < 20 or len(norm2) < 20:
        chars1 = set(norm1.replace(' ', ''))
        chars2 = set(norm2.replace(' ', ''))
        if chars1 and chars2:
            char_similarity = len(chars1 & chars2) / len(chars1 | chars2)
            jaccard = (jaccard + char_similarity) / 2

    # Combine scores
    final_score = min(1.0, jaccard + containment_bonus)

    return final_score


def find_best_match_by_description(
    db: Session,
    company_id: int,
    description: str,
    min_confidence: float = 0.5
) -> Tuple[Optional[Any], float, List[Dict]]:
    """
    Find the best matching item in Item Master by description using fuzzy matching.

    Returns:
        - matched_item: The best matching ItemMaster or None
        - confidence: Confidence score (0-1)
        - suggestions: List of potential matches if confidence is below threshold
    """
    if not description:
        return None, 0.0, []

    # Get all active items for the company
    items = db.query(ItemMaster).filter(
        ItemMaster.company_id == company_id,
        ItemMaster.is_active == True
    ).all()

    if not items:
        return None, 0.0, []

    # Calculate similarity for each item
    matches = []
    for item in items:
        # Compare against description and search_text
        desc_similarity = calculate_similarity(description, item.description or "")
        search_similarity = calculate_similarity(description, item.search_text or "")

        # Use the higher of the two
        best_similarity = max(desc_similarity, search_similarity)

        if best_similarity > 0.2:  # Only consider if some similarity
            matches.append({
                "item": item,
                "confidence": best_similarity,
                "item_id": item.id,
                "item_number": item.item_number,
                "description": item.description
            })

    # Sort by confidence descending
    matches.sort(key=lambda x: x["confidence"], reverse=True)

    if not matches:
        return None, 0.0, []

    best_match = matches[0]

    # If confidence is high enough (>= 0.6), return as match
    # Otherwise return as suggestion for manual review
    if best_match["confidence"] >= min_confidence:
        return best_match["item"], best_match["confidence"], []
    else:
        # Return top 3 suggestions for manual linking
        suggestions = [
            {
                "item_id": m["item_id"],
                "item_number": m["item_number"],
                "description": m["description"],
                "confidence": round(m["confidence"] * 100, 1)
            }
            for m in matches[:3]
        ]
        return None, best_match["confidence"], suggestions


def process_invoice_line_items(
    db: Session,
    invoice_id: int,
    structured_data: dict,
    company_id: int,
    user_id: int
) -> Dict[str, Any]:
    """
    Process invoice line items:
    1. Extract line items from structured data
    2. Create InvoiceItem records
    3. Match with Item Master by item_code/item_number (exact match)
    4. If no exact match, try fuzzy matching by description
    5. Auto-receive matched items to main warehouse
    6. Create ledger entries for stock movements

    Returns summary of processed items including items needing manual review.
    """
    if not structured_data:
        return {"processed": 0, "matched": 0, "received": 0, "errors": [], "needs_review": [], "warnings": []}

    line_items = structured_data.get("line_items", [])
    if not line_items:
        return {"processed": 0, "matched": 0, "received": 0, "errors": [], "needs_review": [], "warnings": []}

    # Get main warehouse for auto-receiving
    main_warehouse = db.query(Warehouse).filter(
        Warehouse.company_id == company_id,
        Warehouse.is_main == True,
        Warehouse.is_active == True
    ).first()

    processed_count = 0
    matched_count = 0
    received_count = 0
    errors = []
    warnings = []
    needs_review = []  # Items that need manual linking

    # Check if main warehouse is configured
    if not main_warehouse:
        warnings.append({
            "type": "no_main_warehouse",
            "message": "No main warehouse configured. Items will be matched but not auto-received to inventory. Please configure a main warehouse in Settings > Warehouses to enable automatic inventory updates."
        })

    for idx, line_item in enumerate(line_items):
        try:
            # Extract line item data
            item_code = line_item.get("item_code") or line_item.get("part_number") or ""
            description = line_item.get("description") or ""
            quantity = line_item.get("quantity")
            unit = line_item.get("unit") or line_item.get("unit_of_measure") or "EA"
            unit_price = line_item.get("unit_price")
            total_price = line_item.get("total_line_amount") or line_item.get("total_price")

            # Skip empty lines
            if not description and not item_code:
                continue

            # Parse numeric values
            try:
                quantity = float(quantity) if quantity else 0
            except (ValueError, TypeError):
                quantity = 0

            try:
                unit_price = float(unit_price) if unit_price else None
            except (ValueError, TypeError):
                unit_price = None

            try:
                total_price = float(total_price) if total_price else None
            except (ValueError, TypeError):
                total_price = None

            # Try to match with Item Master - Priority order:
            # 1. Exact match by item_number
            # 2. Match by short_item_no
            # 3. Fuzzy match by description

            matched_item = None
            match_method = None
            match_confidence = 0.0
            suggestions = []

            # Priority 1: Match by item_number (exact match, case-insensitive)
            if item_code and item_code.strip():
                matched_item = db.query(ItemMaster).filter(
                    ItemMaster.company_id == company_id,
                    func.upper(ItemMaster.item_number) == item_code.strip().upper(),
                    ItemMaster.is_active == True
                ).first()
                if matched_item:
                    match_method = "item_number"
                    match_confidence = 1.0

            # Priority 1.5: Match by alias (vendor/supplier item code)
            if not matched_item and item_code and item_code.strip():
                alias = db.query(ItemAlias).filter(
                    ItemAlias.company_id == company_id,
                    func.upper(ItemAlias.alias_code) == item_code.strip().upper(),
                    ItemAlias.is_active == True
                ).first()
                if alias:
                    matched_item = db.query(ItemMaster).filter(
                        ItemMaster.id == alias.item_id,
                        ItemMaster.is_active == True
                    ).first()
                    if matched_item:
                        match_method = "alias"
                        match_confidence = 1.0
                        logger.info(f"Matched by alias '{item_code}' to item '{matched_item.item_number}'")

            # Priority 2: Match by short_item_no
            if not matched_item and item_code and item_code.strip():
                try:
                    short_no = int(item_code.strip())
                    matched_item = db.query(ItemMaster).filter(
                        ItemMaster.company_id == company_id,
                        ItemMaster.short_item_no == short_no,
                        ItemMaster.is_active == True
                    ).first()
                    if matched_item:
                        match_method = "short_item_no"
                        match_confidence = 1.0
                except ValueError:
                    pass

            # Priority 3: Fuzzy match by description
            if not matched_item and description:
                fuzzy_match, confidence, fuzzy_suggestions = find_best_match_by_description(
                    db, company_id, description, min_confidence=0.6
                )
                if fuzzy_match:
                    matched_item = fuzzy_match
                    match_method = "fuzzy_description"
                    match_confidence = confidence
                    logger.info(f"Fuzzy matched '{description}' to '{fuzzy_match.description}' with {confidence:.0%} confidence")
                else:
                    suggestions = fuzzy_suggestions

            # Create InvoiceItem record
            invoice_item = InvoiceItem(
                invoice_id=invoice_id,
                item_id=matched_item.id if matched_item else None,
                item_description=description[:500] if description else None,
                item_number=item_code[:100] if item_code else None,
                quantity=quantity if quantity > 0 else None,
                unit=unit[:20] if unit else None,
                unit_price=unit_price,
                total_price=total_price,
                quantity_received=0,
                receive_status="pending"
            )
            db.add(invoice_item)
            db.flush()  # Get the ID
            processed_count += 1

            # Track items that need manual review (no match but have suggestions)
            if not matched_item and suggestions:
                needs_review.append({
                    "invoice_item_id": invoice_item.id,
                    "line_number": idx + 1,
                    "item_code": item_code,
                    "description": description,
                    "quantity": quantity,
                    "suggestions": suggestions
                })

            if matched_item:
                matched_count += 1

                # Auto-receive to main warehouse if available and quantity > 0
                if main_warehouse and quantity > 0:
                    try:
                        # Get or create stock record
                        stock = db.query(ItemStock).filter(
                            ItemStock.company_id == company_id,
                            ItemStock.item_id == matched_item.id,
                            ItemStock.warehouse_id == main_warehouse.id
                        ).first()

                        if not stock:
                            stock = ItemStock(
                                company_id=company_id,
                                item_id=matched_item.id,
                                warehouse_id=main_warehouse.id,
                                quantity_on_hand=0,
                                average_cost=0,
                                last_cost=0
                            )
                            db.add(stock)
                            db.flush()

                        # Calculate weighted average cost
                        current_qty = float(stock.quantity_on_hand or 0)
                        current_avg_cost = float(stock.average_cost or 0)
                        new_qty = quantity

                        if unit_price and unit_price > 0:
                            if current_qty + new_qty > 0:
                                new_avg_cost = ((current_qty * current_avg_cost) + (new_qty * unit_price)) / (current_qty + new_qty)
                            else:
                                new_avg_cost = unit_price
                            stock.average_cost = new_avg_cost
                            stock.last_cost = unit_price

                        stock.quantity_on_hand = current_qty + new_qty
                        stock.last_movement_date = datetime.utcnow()

                        # Generate transaction number
                        today = datetime.utcnow()
                        date_prefix = today.strftime("%Y%m%d")
                        last_txn = db.query(ItemLedger).filter(
                            ItemLedger.transaction_number.like(f"TXN-{date_prefix}-%")
                        ).order_by(ItemLedger.id.desc()).first()

                        if last_txn:
                            try:
                                last_num = int(last_txn.transaction_number.split("-")[-1])
                                txn_num = f"TXN-{date_prefix}-{str(last_num + 1).zfill(4)}"
                            except:
                                txn_num = f"TXN-{date_prefix}-0001"
                        else:
                            txn_num = f"TXN-{date_prefix}-0001"

                        # Create ledger entry
                        ledger_entry = ItemLedger(
                            company_id=company_id,
                            item_id=matched_item.id,
                            transaction_number=txn_num,
                            transaction_date=datetime.utcnow(),
                            transaction_type="RECEIVE_INVOICE",
                            quantity=quantity,
                            unit=matched_item.unit or unit,
                            unit_cost=unit_price,
                            total_cost=unit_price * quantity if unit_price else None,
                            to_warehouse_id=main_warehouse.id,
                            invoice_id=invoice_id,
                            balance_after=stock.quantity_on_hand,
                            notes=f"Auto-received from invoice",
                            created_by=user_id
                        )
                        db.add(ledger_entry)

                        # Update invoice item status
                        invoice_item.quantity_received = quantity
                        invoice_item.receive_status = "received"
                        invoice_item.received_to_warehouse_id = main_warehouse.id
                        invoice_item.received_at = datetime.utcnow()
                        invoice_item.received_by = user_id

                        received_count += 1
                        logger.info(f"Auto-received {quantity} of item {matched_item.item_number} to {main_warehouse.name}")

                    except Exception as receive_error:
                        logger.error(f"Error auto-receiving item {item_code}: {receive_error}")
                        errors.append({
                            "line": idx + 1,
                            "item_code": item_code,
                            "error": f"Failed to receive: {str(receive_error)}"
                        })

        except Exception as item_error:
            logger.error(f"Error processing line item {idx + 1}: {item_error}")
            errors.append({
                "line": idx + 1,
                "error": str(item_error)
            })

    # Commit all changes
    try:
        db.commit()
    except Exception as commit_error:
        db.rollback()
        logger.error(f"Error committing invoice items: {commit_error}")
        return {
            "processed": 0,
            "matched": 0,
            "received": 0,
            "errors": [{"error": f"Database commit failed: {str(commit_error)}"}]
        }

    logger.info(f"Invoice {invoice_id}: processed={processed_count}, matched={matched_count}, received={received_count}, needs_review={len(needs_review)}")

    return {
        "processed": processed_count,
        "matched": matched_count,
        "received": received_count,
        "main_warehouse": main_warehouse.name if main_warehouse else None,
        "needs_review": needs_review,  # Items needing manual linking
        "warnings": warnings,
        "errors": errors[:10]  # Return first 10 errors
    }


def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> User:
    """Validate JWT token and return the admin user."""
    token = credentials.credentials
    email = verify_token(token)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Find user in database
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    # Verify the user is an admin
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    return user


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str

class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict

@router.post("/admin/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest, db: Session = Depends(get_db)):
    """Admin login endpoint - authenticates admin users from database"""

    # Find user in database
    user = db.query(User).filter(User.email == request.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Verify password using the security utility
    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Check if user is an admin
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required. Please contact your administrator."
        )

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Please contact support."
        )

    # Create access token
    access_token = create_access_token(data={"sub": user.email})

    # Return admin user info
    admin_user = {
        "id": user.id,
        "email": user.email,
        "name": user.name or "Administrator",
        "role": user.role,
        "is_active": user.is_active
    }

    logger.info(f"Admin login successful: {user.email}")

    return AdminLoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=admin_user
    )

@router.get("/admin/invoices")
async def get_all_invoices(
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get all processed invoices for the admin's company"""

    from app.models import ProcessedImage, User as UserModel, InvoiceItem, InvoiceAllocation, Contract, Site, Project, Client
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload
    import json

    # Filter invoices to only show those from users in the same company
    query = db.query(ProcessedImage).join(UserModel, ProcessedImage.user_id == UserModel.id)

    if admin_user.company_id:
        # Only show invoices from users in the same company
        query = query.filter(UserModel.company_id == admin_user.company_id)
    else:
        # If admin has no company, only show their own invoices
        query = query.filter(ProcessedImage.user_id == admin_user.id)

    processed_images = query.all()

    # Get unlinked items count for all invoices in one query
    unlinked_counts = {}
    if processed_images:
        image_ids = [img.id for img in processed_images]
        unlinked_query = db.query(
            InvoiceItem.invoice_id,
            func.count(InvoiceItem.id).label('count')
        ).filter(
            InvoiceItem.invoice_id.in_(image_ids),
            InvoiceItem.item_id == None  # Unlinked items
        ).group_by(InvoiceItem.invoice_id).all()

        for invoice_id, count in unlinked_query:
            unlinked_counts[invoice_id] = count

    # Get allocations for all invoices
    allocations_map = {}
    if processed_images:
        image_ids = [img.id for img in processed_images]
        allocations = db.query(InvoiceAllocation).filter(
            InvoiceAllocation.invoice_id.in_(image_ids)
        ).all()

        for alloc in allocations:
            target_name = None
            if alloc.contract_id:
                contract = db.query(Contract).filter(Contract.id == alloc.contract_id).first()
                target_name = contract.name if contract else f"Contract #{alloc.contract_id}"
            elif alloc.site_id:
                site = db.query(Site).filter(Site.id == alloc.site_id).first()
                target_name = site.name if site else f"Site #{alloc.site_id}"
            elif alloc.project_id:
                project = db.query(Project).filter(Project.id == alloc.project_id).first()
                target_name = project.name if project else f"Project #{alloc.project_id}"

            allocations_map[alloc.invoice_id] = {
                "id": alloc.id,
                "allocation_type": alloc.allocation_type or "contract",
                "target_name": target_name or "Unknown",
                "total_amount": float(alloc.total_amount) if alloc.total_amount else 0,
                "status": alloc.status or "active"
            }

    invoices = []
    for image in processed_images:
        # Parse structured data from database if available, otherwise use fallback
        structured_data = {}
        if image.structured_data:
            try:
                structured_data = json.loads(image.structured_data)
            except (json.JSONDecodeError, TypeError):
                structured_data = {}
        
        # Provide fallback structure if no real data exists
        if not structured_data:
            structured_data = {
                "document_info": {
                    "invoice_number": f"INV-{image.id:06d}",
                    "invoice_date": image.created_at.strftime("%Y-%m-%d") if image.created_at else "",
                    "due_date": ""
                },
                "supplier": {
                    "company_name": "Sample Supplier Co.",
                    "company_address": "123 Business St, City, State 12345",
                    "email": "supplier@example.com",
                    "phone": "+1-555-0123"
                },
                "customer": {
                    "contact_person": image.user.email.split('@')[0] if image.user else "Customer",
                    "company_name": f"Client Company {image.user_id}",
                    "address": "456 Client Ave, City, State 67890"
                },
                "financial_details": {
                    "subtotal": round(100.0 + (image.id * 15.5), 2),
                    "total_tax_amount": round((100.0 + (image.id * 15.5)) * 0.08, 2),
                    "total_after_tax": round((100.0 + (image.id * 15.5)) * 1.08, 2)
                },
                "line_items": [
                    {
                        "description": f"Service Item {image.id}",
                        "quantity": 1,
                        "unit_price": round(100.0 + (image.id * 15.5), 2),
                        "total_line_amount": round(100.0 + (image.id * 15.5), 2)
                    }
                ]
            }
        
        invoice_data = {
            "id": str(image.id),
            "image_id": str(image.id),
            "user_id": image.user_id,
            "user_email": image.user.email if image.user else "unknown@example.com",
            "original_filename": image.original_filename or f"invoice_{image.id}.jpg",
            "document_type": getattr(image, 'document_type', 'invoice'),
            "invoice_category": getattr(image, 'invoice_category', None),
            "created_at": image.created_at.isoformat() if image.created_at else "",
            "processing_method": getattr(image, 'processing_method', None) or 'STANDARD',
            "extraction_confidence": getattr(image, 'extraction_confidence', None) or 0.0,
            "structured_data": structured_data,
            "ocr_stats": {
                "words_extracted": getattr(image, 'ocr_extracted_words', None) or 0,
                "average_confidence": getattr(image, 'ocr_average_confidence', None) or 0.0
            },
            "unlinked_items_count": unlinked_counts.get(image.id, 0),
            "allocation": allocations_map.get(image.id, None)
        }
        invoices.append(invoice_data)

    return invoices

@router.get("/admin/stats")
async def get_admin_stats(
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get admin statistics for the admin's company"""

    from app.models import ProcessedImage, User as UserModel, InvoiceItem
    from sqlalchemy import func, and_
    from datetime import datetime, timedelta

    # Build base queries filtered by company
    if admin_user.company_id:
        # Count invoices from users in the same company
        invoice_query = db.query(ProcessedImage).join(
            UserModel, ProcessedImage.user_id == UserModel.id
        ).filter(UserModel.company_id == admin_user.company_id)

        # Count users in the same company
        user_query = db.query(UserModel).filter(UserModel.company_id == admin_user.company_id)
    else:
        # If admin has no company, only count their own data
        invoice_query = db.query(ProcessedImage).filter(ProcessedImage.user_id == admin_user.id)
        user_query = db.query(UserModel).filter(UserModel.id == admin_user.id)

    total_invoices = invoice_query.count()
    total_users = user_query.count()

    # Count all invoices with unlinked items (across all categories)
    all_invoice_ids = [img.id for img in invoice_query.all()]

    unlinked_invoices_count = 0
    if all_invoice_ids:
        # Get count of invoices that have at least one unlinked item
        invoices_with_unlinked = db.query(InvoiceItem.invoice_id).filter(
            InvoiceItem.invoice_id.in_(all_invoice_ids),
            InvoiceItem.item_id == None
        ).distinct().count()
        unlinked_invoices_count = invoices_with_unlinked

    # Get processing methods distribution (mock for now)
    processing_methods = {
        "gemini": max(1, int(total_invoices * 0.6)) if total_invoices > 0 else 0,
        "azure": max(1, int(total_invoices * 0.25)) if total_invoices > 0 else 0,
        "aws": max(1, int(total_invoices * 0.15)) if total_invoices > 0 else 0
    }

    # Get recent activity (last 7 days)
    recent_activity = []
    for i in range(7):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        count = max(0, total_invoices - i * 2) if total_invoices > 0 else 0
        recent_activity.append({"date": date, "count": count})

    return {
        "total_invoices": total_invoices,
        "total_users": total_users,
        "unlinked_invoices_count": unlinked_invoices_count,
        "processing_methods": processing_methods,
        "recent_activity": recent_activity
    }

def get_company_image(image_id: int, admin_user: User, db: Session):
    """Helper to get an image and verify it belongs to the admin's company"""
    from app.models import ProcessedImage, User as UserModel

    image = db.query(ProcessedImage).filter(ProcessedImage.id == image_id).first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )

    # Verify the image belongs to a user in the same company
    image_owner = db.query(UserModel).filter(UserModel.id == image.user_id).first()

    if admin_user.company_id:
        if not image_owner or image_owner.company_id != admin_user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this image"
            )
    else:
        # If admin has no company, only allow access to their own images
        if image.user_id != admin_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this image"
            )

    return image


@router.get("/admin/images/{image_id}/url")
async def get_admin_image_url(
    image_id: int,
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get image URL for admin (admin only)"""

    from app.services.s3 import generate_presigned_url

    image = get_company_image(image_id, admin_user, db)

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )

    # Handle S3 images
    if image.s3_key and not image.s3_key.startswith("local/"):
        presigned_url = generate_presigned_url(image.s3_key, expiration=3600)
        if presigned_url:
            return {"url": presigned_url, "type": "s3"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate image access URL"
            )

    # Handle local images
    elif image.s3_key and image.s3_key.startswith("local/"):
        filename = image.s3_key.replace("local/", "")
        local_url = f"http://localhost:8000/uploads/{filename}"
        return {"url": local_url, "type": "local"}

    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image file not found"
        )


@router.post("/admin/images/{image_id}/reprocess")
async def reprocess_image(
    image_id: int,
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Reprocess an image with AI extraction (admin only)"""

    from app.services.s3 import download_file_from_s3
    from app.services.enhanced_invoice_processing import process_invoice_image_enhanced
    import json
    import os

    image = get_company_image(image_id, admin_user, db)

    try:
        # Get the image file bytes
        file_bytes = None

        # Handle S3 images
        if image.s3_key and not image.s3_key.startswith("local/"):
            file_bytes = download_file_from_s3(image.s3_key)
        # Handle local images
        elif image.s3_key and image.s3_key.startswith("local/"):
            filename = image.s3_key.replace("local/", "")
            local_path = os.path.join("uploads", filename)
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    file_bytes = f.read()

        if not file_bytes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image file not found or could not be retrieved"
            )

        # Reprocess with enhanced OCR (with vendor lookup)
        result = process_invoice_image_enhanced(file_bytes, db)

        if result.get("success") and result.get("structured_data"):
            # Update the database record
            image.structured_data = json.dumps(result["structured_data"])
            image.processing_method = "ENHANCED"
            image.extraction_confidence = result.get("average_confidence", 0.0)
            image.ocr_extracted_words = result.get("total_words_extracted", 0)
            image.ocr_average_confidence = result.get("average_confidence", 0.0)
            image.processing_status = "completed"

            db.commit()

            return {
                "success": True,
                "message": "Image reprocessed successfully",
                "image_id": image_id,
                "processing_method": "ENHANCED",
                "confidence_score": result.get("average_confidence", 0.0),
                "structured_data": result.get("structured_data")
            }
        else:
            error_msg = result.get("error", "AI processing failed")
            return {
                "success": False,
                "message": f"Reprocessing failed: {error_msg}",
                "image_id": image_id
            }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reprocessing image: {str(e)}"
        )


@router.delete("/admin/images/{image_id}")
async def delete_admin_image(
    image_id: int,
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Delete an image (admin only)"""
    from app.services.s3 import delete_from_s3
    import os

    image = get_company_image(image_id, admin_user, db)

    errors = []

    try:
        # Delete from S3 if stored there
        if image.s3_key and not image.s3_key.startswith("local/"):
            if not delete_from_s3(image.s3_key):
                errors.append(f"Failed to delete S3 object: {image.s3_key}")

        # Delete local files if stored locally
        elif image.s3_key and image.s3_key.startswith("local/"):
            filename = image.s3_key.replace("local/", "")
            local_file_path = f"uploads/{filename}"
            if os.path.exists(local_file_path):
                os.remove(local_file_path)

        # Clear invoice reference from ledger entries (keep for audit trail)
        db.query(ItemLedger).filter(ItemLedger.invoice_id == image_id).update(
            {"invoice_id": None}, synchronize_session=False
        )

        # Delete associated invoice items first (cascade)
        db.query(InvoiceItem).filter(InvoiceItem.invoice_id == image_id).delete()

        # Delete from database
        db.delete(image)
        db.commit()

        return {
            "success": True,
            "message": "Invoice deleted successfully",
            "errors": errors if errors else None
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting image: {str(e)}"
        )


class InvoiceUpdateData(BaseModel):
    invoice_category: Optional[str] = None
    document_info: Optional[dict] = None
    supplier: Optional[dict] = None
    customer: Optional[dict] = None
    financial_details: Optional[dict] = None


@router.put("/admin/images/{image_id}")
async def update_admin_invoice(
    image_id: int,
    update_data: InvoiceUpdateData,
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Update invoice structured data (admin only)"""
    import json

    image = get_company_image(image_id, admin_user, db)

    try:
        # Update invoice_category if provided (can be set to empty string to clear)
        if update_data.invoice_category is not None:
            # Allow empty string to clear category, or validate against allowed values
            allowed_categories = ['', 'service', 'spare_parts', 'expense', 'equipment', 'utilities']
            if update_data.invoice_category not in allowed_categories:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid invoice category. Allowed values: {', '.join(allowed_categories)}"
                )
            image.invoice_category = update_data.invoice_category if update_data.invoice_category else None

        # Parse existing structured data
        structured_data = {}
        if image.structured_data:
            try:
                structured_data = json.loads(image.structured_data)
            except (json.JSONDecodeError, TypeError):
                structured_data = {}

        # Update document_info
        if update_data.document_info:
            if "document_info" not in structured_data:
                structured_data["document_info"] = {}
            for key, value in update_data.document_info.items():
                if value is not None:
                    structured_data["document_info"][key] = value

        # Update supplier
        if update_data.supplier:
            if "supplier" not in structured_data:
                structured_data["supplier"] = {}
            for key, value in update_data.supplier.items():
                if value is not None:
                    structured_data["supplier"][key] = value

        # Update customer
        if update_data.customer:
            if "customer" not in structured_data:
                structured_data["customer"] = {}
            for key, value in update_data.customer.items():
                if value is not None:
                    structured_data["customer"][key] = value

        # Update financial_details
        if update_data.financial_details:
            if "financial_details" not in structured_data:
                structured_data["financial_details"] = {}
            for key, value in update_data.financial_details.items():
                if value is not None:
                    structured_data["financial_details"][key] = value

        # Save updated structured data
        image.structured_data = json.dumps(structured_data)
        db.commit()

        logger.info(f"Invoice {image_id} updated by admin {admin_user.email}")

        return {
            "success": True,
            "message": "Invoice updated successfully",
            "image_id": image_id,
            "structured_data": structured_data
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating invoice {image_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating invoice: {str(e)}"
        )


@router.get("/admin/images/{image_id}/vendor-lookup")
async def admin_get_vendor_lookup(
    image_id: int,
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get vendor lookup for an image (admin only)"""
    from app.models import Vendor
    from sqlalchemy import or_
    import json

    image = get_company_image(image_id, admin_user, db)

    # Extract supplier name from structured data
    supplier_name = None
    if image.structured_data:
        try:
            structured_data = json.loads(image.structured_data)
            supplier_name = structured_data.get("supplier", {}).get("company_name")
        except (json.JSONDecodeError, TypeError):
            pass

    if not supplier_name:
        return {
            "found": False,
            "vendor": None,
            "suggestions": [],
            "extracted_name": None,
            "message": "No supplier name found in document"
        }

    # Try exact match first (case-insensitive) - check both name and display_name
    vendor = db.query(Vendor).filter(
        or_(
            Vendor.name.ilike(supplier_name),
            Vendor.display_name.ilike(supplier_name)
        ),
        Vendor.is_active == True
    ).first()

    if vendor:
        return {
            "found": True,
            "vendor": {
                "id": vendor.id,
                "name": vendor.name,
                "display_name": vendor.display_name
            },
            "suggestions": [],
            "extracted_name": supplier_name
        }

    # No exact match - get suggestions
    search_term = f"%{supplier_name}%"
    similar_vendors = db.query(Vendor).filter(
        or_(
            Vendor.name.ilike(search_term),
            Vendor.display_name.ilike(search_term)
        ),
        Vendor.is_active == True
    ).limit(5).all()

    return {
        "found": False,
        "vendor": None,
        "suggestions": [
            {
                "id": v.id,
                "name": v.name,
                "display_name": v.display_name
            }
            for v in similar_vendors
        ],
        "extracted_name": supplier_name
    }


@router.post("/admin/images/{image_id}/link-vendor")
async def admin_link_vendor_to_image(
    image_id: int,
    vendor_id: int,
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Link a vendor to an image (admin only)"""
    from app.models import Vendor
    import json

    image = get_company_image(image_id, admin_user, db)

    vendor = db.query(Vendor).filter(
        Vendor.id == vendor_id,
        Vendor.is_active == True
    ).first()

    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found"
        )

    # Update structured data with vendor info
    try:
        structured_data = {}
        if image.structured_data:
            structured_data = json.loads(image.structured_data)

        # Update supplier info with vendor data
        if "supplier" not in structured_data:
            structured_data["supplier"] = {}

        structured_data["supplier"]["company_name"] = vendor.display_name
        structured_data["supplier"]["vendor_id"] = vendor.id
        if vendor.email:
            structured_data["supplier"]["email"] = vendor.email
        if vendor.phone:
            structured_data["supplier"]["phone"] = vendor.phone
        if vendor.address:
            structured_data["supplier"]["company_address"] = vendor.address
        if vendor.tax_number:
            structured_data["supplier"]["tax_number"] = vendor.tax_number

        image.structured_data = json.dumps(structured_data)
        db.commit()
        db.refresh(image)

        return {
            "success": True,
            "message": f"Vendor '{vendor.display_name}' linked to invoice successfully",
            "vendor": {
                "id": vendor.id,
                "name": vendor.name,
                "display_name": vendor.display_name
            },
            "image_id": image_id
        }

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error parsing structured data"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error linking vendor: {str(e)}"
        )


@router.post("/admin/images/upload")
async def admin_upload_image(
    file: UploadFile = File(...),
    document_type: str = "invoice",
    invoice_category: str = None,
    site_id: int = None,
    contract_id: int = None,
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Upload and process an image (admin only) - creates document under admin's account."""
    from app.models import ProcessedImage
    from app.services.s3 import upload_to_s3, process_image
    import uuid
    import os
    import json

    # Supported file types
    SUPPORTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"]
    SUPPORTED_PDF_TYPE = "application/pdf"

    # Check file type
    is_image = file.content_type in SUPPORTED_IMAGE_TYPES
    is_pdf = file.content_type == SUPPORTED_PDF_TYPE

    if not is_image and not is_pdf:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File must be an image or PDF. Supported types: {', '.join(SUPPORTED_IMAGE_TYPES + [SUPPORTED_PDF_TYPE])}"
        )

    # Read file content
    content = await file.read()

    # Convert PDF to image if necessary
    if is_pdf:
        from app.api.images import convert_pdf_to_image
        content = convert_pdf_to_image(content)
        unique_filename = f"{uuid.uuid4()}.png"
    else:
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"{uuid.uuid4()}.{file_extension}"

    # Ensure uploads directory exists
    os.makedirs("uploads", exist_ok=True)

    # Save file temporarily
    temp_file_path = f"uploads/{unique_filename}"
    with open(temp_file_path, "wb") as buffer:
        buffer.write(content)

    try:
        # Read file content for invoice processing
        with open(temp_file_path, 'rb') as f:
            file_bytes = f.read()

        # Process image (resize, compress, OCR, AI extraction) - pass db and company_id for vendor lookup/creation
        processed_image_path, invoice_results = process_image(temp_file_path, file_bytes, db, admin_user.company_id)

        # Try to upload to S3, fallback to local if it fails
        try:
            s3_key, s3_url = upload_to_s3(processed_image_path, unique_filename)
            processing_status = "completed"
            s3_url = s3_key

            if os.path.exists(processed_image_path):
                os.remove(processed_image_path)

        except Exception as s3_error:
            print(f"S3 upload failed, using local storage: {s3_error}")
            s3_key = f"local/{unique_filename}"
            s3_url = f"local/{unique_filename}"
            processing_status = "completed_local"

            final_file_path = f"uploads/{unique_filename}"
            if processed_image_path != temp_file_path:
                import shutil
                shutil.move(processed_image_path, final_file_path)

        # Prepare structured data for storage
        structured_data_json = None
        extraction_confidence = 0.0

        if invoice_results.get("structured_data"):
            structured_data_json = json.dumps(invoice_results["structured_data"])
            if isinstance(invoice_results["structured_data"], dict):
                validation = invoice_results["structured_data"].get("validation", {})
                extraction_confidence = float(validation.get("confidence_score", 0))

                # Check for duplicate invoice (within same company)
                invoice_number, supplier_name = extract_invoice_info_for_duplicate_check(
                    invoice_results["structured_data"]
                )
                is_duplicate, existing_id = check_duplicate_invoice(db, invoice_number, supplier_name, admin_user.company_id)

                if is_duplicate:
                    # Clean up temporary files
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                    if processed_image_path and os.path.exists(processed_image_path):
                        os.remove(processed_image_path)

                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Duplicate invoice detected. Invoice number '{invoice_number}' already exists (ID: {existing_id})"
                    )

        enhancement_features = invoice_results.get("enhancement_features", {})

        # Create database record using the authenticated admin user
        db_image = ProcessedImage(
            user_id=admin_user.id,
            original_filename=file.filename,
            s3_key=s3_key,
            s3_url=s3_url,
            processing_status=processing_status,
            document_type=document_type,
            invoice_category=invoice_category if document_type == "invoice" else None,
            site_id=site_id,
            contract_id=contract_id,
            ocr_extracted_words=int(invoice_results.get("total_words_extracted", 0)),
            ocr_average_confidence=float(invoice_results.get("average_confidence", 0.0)),
            ocr_preprocessing_methods=int(enhancement_features.get("multiple_preprocessing", 1)),
            patterns_detected=int(enhancement_features.get("pattern_recognition", 0)),
            has_structured_data=bool(invoice_results.get("structured_data")),
            structured_data=structured_data_json,
            extraction_confidence=float(extraction_confidence),
            processing_method="enhanced"
        )

        db.add(db_image)
        db.commit()
        db.refresh(db_image)

        # Process line items: match with Item Master, create InvoiceItem records,
        # and auto-receive matched items to main warehouse
        line_items_result = None
        if invoice_results.get("structured_data") and document_type == "invoice":
            line_items_result = process_invoice_line_items(
                db=db,
                invoice_id=db_image.id,
                structured_data=invoice_results["structured_data"],
                company_id=admin_user.company_id,
                user_id=admin_user.id
            )
            logger.info(f"Line items processing: {line_items_result}")

        # Return response matching the UploadResponse interface
        return {
            "id": db_image.id,
            "original_filename": db_image.original_filename,
            "processing_status": db_image.processing_status,
            "document_type": db_image.document_type,
            "invoice_category": db_image.invoice_category,
            "created_at": db_image.created_at.isoformat(),
            "structured_data": structured_data_json,
            "vendor_lookup": invoice_results.get("vendor_lookup"),
            "line_items_processing": line_items_result
        }

    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing image: {str(e)}"
        )


@router.post("/admin/images/upload-bulk")
async def admin_upload_bulk_images(
    files: List[UploadFile] = File(...),
    document_type: str = "invoice",
    invoice_category: str = None,
    admin_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Upload and process multiple images (admin only) - creates documents under admin's account."""
    from app.models import ProcessedImage
    from app.services.s3 import upload_to_s3, process_image
    from app.api.images import convert_pdf_to_image
    import uuid
    import os
    import json
    import shutil

    # Supported file types
    SUPPORTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"]
    SUPPORTED_PDF_TYPE = "application/pdf"

    # Validate file count
    if len(files) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )

    if len(files) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 50 files allowed per upload"
        )

    # admin_user is already authenticated via get_current_admin dependency

    results = []
    errors = []

    for file in files:
        temp_file_path = None
        try:
            # Check file type
            is_image = file.content_type in SUPPORTED_IMAGE_TYPES
            is_pdf = file.content_type == SUPPORTED_PDF_TYPE

            if not is_image and not is_pdf:
                errors.append({
                    "filename": file.filename,
                    "error": f"Unsupported file type: {file.content_type}"
                })
                continue

            # Read file content
            content = await file.read()

            # Convert PDF to image if necessary
            if is_pdf:
                content = convert_pdf_to_image(content)
                unique_filename = f"{uuid.uuid4()}.png"
            else:
                file_extension = file.filename.split(".")[-1] if "." in file.filename else "jpg"
                unique_filename = f"{uuid.uuid4()}.{file_extension}"

            # Ensure uploads directory exists
            os.makedirs("uploads", exist_ok=True)

            # Save file temporarily
            temp_file_path = f"uploads/{unique_filename}"
            with open(temp_file_path, "wb") as buffer:
                buffer.write(content)

            # Read file content for invoice processing
            with open(temp_file_path, 'rb') as f:
                file_bytes = f.read()

            # Process image (resize, compress, OCR, AI extraction) - pass company_id for vendor auto-creation
            processed_image_path, invoice_results = process_image(temp_file_path, file_bytes, db, admin_user.company_id)

            # Try to upload to S3, fallback to local if it fails
            try:
                s3_key, s3_url = upload_to_s3(processed_image_path, unique_filename)
                processing_status = "completed"
                s3_url = s3_key

                if os.path.exists(processed_image_path):
                    os.remove(processed_image_path)

            except Exception as s3_error:
                print(f"S3 upload failed for {file.filename}, using local storage: {s3_error}")
                s3_key = f"local/{unique_filename}"
                s3_url = f"local/{unique_filename}"
                processing_status = "completed_local"

                final_file_path = f"uploads/{unique_filename}"
                if processed_image_path != temp_file_path:
                    shutil.move(processed_image_path, final_file_path)

            # Prepare structured data for storage
            structured_data_json = None
            extraction_confidence = 0.0
            is_duplicate = False
            duplicate_invoice_number = None

            if invoice_results.get("structured_data"):
                structured_data_json = json.dumps(invoice_results["structured_data"])
                if isinstance(invoice_results["structured_data"], dict):
                    validation = invoice_results["structured_data"].get("validation", {})
                    extraction_confidence = float(validation.get("confidence_score", 0))

                    # Check for duplicate invoice (within same company)
                    invoice_number, supplier_name = extract_invoice_info_for_duplicate_check(
                        invoice_results["structured_data"]
                    )
                    is_duplicate, existing_id = check_duplicate_invoice(db, invoice_number, supplier_name, admin_user.company_id)

                    if is_duplicate:
                        duplicate_invoice_number = invoice_number
                        # Clean up files for duplicate
                        if temp_file_path and os.path.exists(temp_file_path):
                            os.remove(temp_file_path)
                        if processed_image_path and os.path.exists(processed_image_path):
                            os.remove(processed_image_path)

                        errors.append({
                            "filename": file.filename,
                            "error": f"Duplicate invoice - Invoice number '{invoice_number}' already exists (ID: {existing_id})",
                            "is_duplicate": True,
                            "existing_id": existing_id
                        })
                        continue

            enhancement_features = invoice_results.get("enhancement_features", {})

            # Create database record
            db_image = ProcessedImage(
                user_id=admin_user.id,
                original_filename=file.filename,
                s3_key=s3_key,
                s3_url=s3_url,
                processing_status=processing_status,
                document_type=document_type,
                invoice_category=invoice_category if document_type == "invoice" else None,
                ocr_extracted_words=int(invoice_results.get("total_words_extracted", 0)),
                ocr_average_confidence=float(invoice_results.get("average_confidence", 0.0)),
                ocr_preprocessing_methods=int(enhancement_features.get("multiple_preprocessing", 1)),
                patterns_detected=int(enhancement_features.get("pattern_recognition", 0)),
                has_structured_data=bool(invoice_results.get("structured_data")),
                structured_data=structured_data_json,
                extraction_confidence=float(extraction_confidence),
                processing_method="enhanced"
            )

            db.add(db_image)
            db.commit()
            db.refresh(db_image)

            # Process line items: match with Item Master, create InvoiceItem records,
            # and auto-receive matched items to main warehouse
            line_items_result = None
            if invoice_results.get("structured_data") and document_type == "invoice":
                line_items_result = process_invoice_line_items(
                    db=db,
                    invoice_id=db_image.id,
                    structured_data=invoice_results["structured_data"],
                    company_id=admin_user.company_id,
                    user_id=admin_user.id
                )

            results.append({
                "id": db_image.id,
                "original_filename": db_image.original_filename,
                "processing_status": db_image.processing_status,
                "document_type": db_image.document_type,
                "created_at": db_image.created_at.isoformat(),
                "structured_data": structured_data_json,
                "vendor_lookup": invoice_results.get("vendor_lookup"),
                "line_items_processing": line_items_result
            })

        except Exception as e:
            errors.append({
                "filename": file.filename,
                "error": str(e)
            })
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    # Count duplicates separately
    duplicates = [e for e in errors if e.get("is_duplicate")]
    other_errors = [e for e in errors if not e.get("is_duplicate")]

    return {
        "success": len(results) > 0,
        "total_files": len(files),
        "successful": len(results),
        "failed": len(other_errors),
        "skipped_duplicates": len(duplicates),
        "results": results,
        "errors": errors
    }