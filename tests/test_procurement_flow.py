#!/usr/bin/env python3
"""
End-to-End Procurement Flow Test
Processes the MRAD ELECTRIC invoice through: PR -> PO -> Invoice -> Goods Receipt

Invoice Details:
- Supplier: MRAD ELECTRIC sal
- Invoice #: SI 82763
- Date: 13/05/2022
- Total: $1,214.23 (including VAT)
"""

import os
import sys
import requests
from datetime import datetime, date, timedelta
from decimal import Decimal

# Configuration
API_URL = os.environ.get("API_URL", "http://localhost:8000/api")
TEST_EMAIL = os.environ.get("TEST_EMAIL", "test@doxsnap.com")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "test123")

# Invoice data from MRAD ELECTRIC (SI 82763)
INVOICE_DATA = {
    "supplier": {
        "name": "MRAD ELECTRIC sal",
        "address": "Ajaltoun - Main Road - MRAD Bldg",
        "phone": "09 23 07 18",
        "fax": "09 23 07 19",
        "email": "info@mradelectricsal.com",
        "tax_id": "3176112-601",
        "capital": "1.500.000.000 LBP"
    },
    "invoice_number": "SI 82763",
    "invoice_date": "2022-05-13",
    "customer": "1525 - M/S MMG",
    "customer_address": "ANTELIAS",
    "delivery_note": "75117",
    "vat_number": "3176112-60",
    "currency": "USD",
    "line_items": [
        {"item_number": "PHLPS 36W/10", "description": "FLUO 36W DAYLIGHT 120CM PHILIPS", "quantity": 95, "unit_price": 1.000, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 10.44, "net_usd": 105.44},
        {"item_number": "PHL STARTER 20W", "description": "STARTER 20W PHILIPS", "quantity": 266, "unit_price": 0.500, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 14.63, "net_usd": 147.63},
        {"item_number": "SYL ST40", "description": "STARTER 4-80W SYLVANIA", "quantity": 79, "unit_price": 0.500, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 4.35, "net_usd": 43.85},
        {"item_number": "OSR DLX D26W/21", "description": "DULUX D BASE G24 26W/21 OSRAM", "quantity": 120, "unit_price": 3.000, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 39.60, "net_usd": 399.60},
        {"item_number": "OSR MR16 7.5W D", "description": "LED MR16 GU5.3 D/L 7.5W OSRAM", "quantity": 60, "unit_price": 1.500, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 9.90, "net_usd": 99.90},
        {"item_number": "LUZ-GU10 6.5 WW", "description": "LAMPE LED 6.5W GU10 W/W", "quantity": 5, "unit_price": 1.900, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 1.05, "net_usd": 10.55},
        {"item_number": "ELT 40W 220V", "description": "BALLAST 220V 40W ELT SPAIN", "quantity": 9, "unit_price": 3.500, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 3.47, "net_usd": 34.97},
        {"item_number": "PHLPS 18W/10", "description": "FLUO 18W DAYLIGHT 60CM PHILIPS", "quantity": 266, "unit_price": 0.900, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 26.33, "net_usd": 265.73},
        {"item_number": "TRANS 26W SCH", "description": "BALLAST 220V 26W SCHWABE", "quantity": 12, "unit_price": 8.000, "discount_pct": 0.5, "vat_pct": 11, "vat_amount": 10.56, "net_usd": 106.56},
    ],
    "totals": {
        "gross_total": 1093.90,
        "net_before_vat": 1093.90,
        "vat_11_pct": 120.33,
        "net_after_vat": 1214.23,
        "vat_ll_equivalent": 181397.48
    }
}

# Track created entities for cleanup
created_ids = {
    "address_book": [],
    "vendors": [],
    "purchase_requests": [],
    "purchase_orders": [],
    "goods_receipts": [],
    "invoices": []
}


def api_request(method, endpoint, token, data=None, files=None):
    """Make API request with error handling"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_URL}/{endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=data)
        elif method == "POST":
            if files:
                response = requests.post(url, headers=headers, data=data, files=files)
            else:
                response = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data)
        elif method == "PATCH":
            response = requests.patch(url, headers=headers, json=data)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            return None, f"Unknown method: {method}"

        return response, None
    except Exception as e:
        return None, str(e)


def authenticate():
    """Get authentication token"""
    print("\n" + "=" * 60)
    print("STEP 0: AUTHENTICATION")
    print("=" * 60)

    try:
        response = requests.post(
            f"{API_URL}/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        if response.status_code in [200, 201]:
            token = response.json().get("access_token")
            print(f"  ✅ Authenticated as {TEST_EMAIL}")
            return token
        else:
            print(f"  ❌ Authentication failed: {response.status_code}")
            print(f"     Response: {response.text}")
            return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def setup_vendor(token):
    """Create or find vendor (MRAD ELECTRIC) in Address Book"""
    print("\n" + "=" * 60)
    print("STEP 1: VENDOR SETUP")
    print("=" * 60)

    supplier = INVOICE_DATA["supplier"]

    # First, check if vendor exists in Address Book
    response, error = api_request("GET", "address-book", token, {
        "search_type": "V",
        "search": "MRAD"
    })

    if response and response.status_code == 200:
        data = response.json()
        entries = data.get("entries", data) if isinstance(data, dict) else data
        if entries and len(entries) > 0:
            vendor = entries[0]
            print(f"  ✅ Found existing vendor: {vendor.get('alpha_name')} (ID: {vendor['id']})")
            return {"id": vendor["id"], "name": vendor.get("alpha_name"), "is_address_book": True}

    # Create new vendor in Address Book
    vendor_data = {
        "search_type": "V",
        "alpha_name": supplier["name"],
        "tax_id": supplier["tax_id"],
        "address_line_1": supplier["address"],
        "phone_primary": supplier["phone"],
        "fax": supplier["fax"],
        "email": supplier["email"],
        "notes": f"Capital: {supplier['capital']}"
    }

    response, error = api_request("POST", "address-book", token, vendor_data)

    if response and response.status_code in [200, 201]:
        data = response.json()
        created_ids["address_book"].append(data["id"])
        print(f"  ✅ Created vendor: {supplier['name']} (ID: {data['id']})")
        print(f"     Address #: {data.get('address_number')}")
        return {"id": data["id"], "name": supplier["name"], "is_address_book": True}

    # Fallback: Try legacy vendors table
    print("  ⚠️ Could not create in Address Book, trying legacy vendors...")
    response, error = api_request("GET", "vendors", token, {"search": "MRAD", "limit": 1})

    if response and response.status_code == 200:
        data = response.json()
        vendors = data.get("vendors", data) if isinstance(data, dict) else data
        if vendors and len(vendors) > 0:
            vendor = vendors[0]
            print(f"  ✅ Found legacy vendor: {vendor.get('name')} (ID: {vendor['id']})")
            return {"id": vendor["id"], "name": vendor.get("name"), "is_address_book": False}

    print("  ❌ Could not find or create vendor")
    return None


def get_or_create_vendor_legacy(token):
    """Get or create vendor in legacy vendors table (needed for PO)"""
    print("\n  Checking legacy vendor table (needed for PO creation)...")

    supplier = INVOICE_DATA["supplier"]

    # Check existing
    response, error = api_request("GET", "vendors", token, {"search": "MRAD", "limit": 1})
    if response and response.status_code == 200:
        data = response.json()
        vendors = data.get("vendors", data) if isinstance(data, dict) else data
        if vendors and len(vendors) > 0:
            vendor = vendors[0]
            print(f"  ✅ Found legacy vendor: {vendor.get('name')} (ID: {vendor['id']})")
            return vendor["id"]

    # Create in legacy vendors
    vendor_data = {
        "name": supplier["name"],
        "display_name": supplier["name"],
        "tax_id": supplier["tax_id"],
        "phone": supplier["phone"],
        "email": supplier["email"],
        "address": supplier["address"]
    }

    response, error = api_request("POST", "vendors", token, vendor_data)
    if response and response.status_code in [200, 201]:
        data = response.json()
        created_ids["vendors"].append(data["id"])
        print(f"  ✅ Created legacy vendor: {supplier['name']} (ID: {data['id']})")
        return data["id"]

    print(f"  ⚠️ Could not create legacy vendor: {response.status_code if response else error}")
    return None


def create_purchase_request(token, vendor_id):
    """Create Purchase Request (PR)"""
    print("\n" + "=" * 60)
    print("STEP 2: CREATE PURCHASE REQUEST (PR)")
    print("=" * 60)

    # Build PR lines from invoice items
    pr_lines = []
    for item in INVOICE_DATA["line_items"]:
        pr_lines.append({
            "item_number": item["item_number"],
            "description": item["description"],
            "quantity_requested": item["quantity"],
            "unit": "EA",
            "estimated_unit_cost": item["unit_price"],
            "notes": f"From Invoice {INVOICE_DATA['invoice_number']}"
        })

    # Calculate estimated total
    estimated_total = sum(item["quantity"] * item["unit_price"] for item in INVOICE_DATA["line_items"])

    pr_data = {
        "title": f"PR from Invoice {INVOICE_DATA['invoice_number']} - {INVOICE_DATA['supplier']['name']}",
        "description": f"Purchase request for electrical supplies from {INVOICE_DATA['supplier']['name']}",
        "vendor_id": vendor_id,
        "priority": "normal",
        "currency": INVOICE_DATA["currency"],
        "required_date": (date.today() + timedelta(days=7)).isoformat(),
        "notes": f"Based on Invoice #{INVOICE_DATA['invoice_number']} dated {INVOICE_DATA['invoice_date']}",
        "lines": pr_lines
    }

    response, error = api_request("POST", "purchase-requests", token, pr_data)

    if error:
        print(f"  ❌ Error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        created_ids["purchase_requests"].append(data["id"])
        print(f"  ✅ Created PR: {data['pr_number']}")
        print(f"     ID: {data['id']}")
        print(f"     Status: {data['status']}")
        print(f"     Lines: {len(pr_lines)} items")
        print(f"     Estimated Total: ${estimated_total:.2f}")
        return data
    else:
        print(f"  ❌ Failed: {response.status_code}")
        print(f"     {response.text[:300]}")
        return None


def submit_and_approve_pr(token, pr_id, pr_number):
    """Submit and approve the PR"""
    print("\n  Submitting PR for approval...")

    # Submit PR
    response, error = api_request("POST", f"purchase-requests/{pr_id}/submit", token)
    if response and response.status_code == 200:
        print(f"  ✅ PR {pr_number} submitted")
    else:
        print(f"  ⚠️ Submit failed: {response.status_code if response else error}")
        return False

    # Approve PR
    print("  Approving PR...")
    response, error = api_request("POST", f"purchase-requests/{pr_id}/approve", token, {
        "notes": "Approved based on existing invoice"
    })
    if response and response.status_code == 200:
        print(f"  ✅ PR {pr_number} approved")
        return True
    else:
        print(f"  ⚠️ Approve failed: {response.status_code if response else error}")
        return False


def convert_pr_to_po(token, pr_id, vendor_id):
    """Convert approved PR to Purchase Order (PO)"""
    print("\n" + "=" * 60)
    print("STEP 3: CONVERT PR TO PURCHASE ORDER (PO)")
    print("=" * 60)

    # Get PR with lines to get line prices
    response, error = api_request("GET", f"purchase-requests/{pr_id}", token)
    if not response or response.status_code != 200:
        print(f"  ❌ Could not get PR details: {error}")
        return None

    pr = response.json()

    # Build line prices map - use invoice prices (net price after discount)
    line_prices = {}
    invoice_items = {item["item_number"]: item for item in INVOICE_DATA["line_items"]}

    for pr_line in pr.get("lines", []):
        item_number = pr_line.get("item_number")
        if item_number in invoice_items:
            inv_item = invoice_items[item_number]
            # Calculate discounted price
            discounted_price = inv_item["unit_price"] * (1 - inv_item["discount_pct"] / 100)
            line_prices[str(pr_line["id"])] = discounted_price

    convert_data = {
        "vendor_id": vendor_id,
        "order_date": date.today().isoformat(),
        "expected_date": (date.today() + timedelta(days=14)).isoformat(),
        "payment_terms": "Net 30",
        "shipping_address": INVOICE_DATA["customer_address"],
        "line_prices": line_prices
    }

    response, error = api_request("POST", f"purchase-requests/{pr_id}/convert-to-po", token, convert_data)

    if error:
        print(f"  ❌ Error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        created_ids["purchase_orders"].append(data["po_id"])
        print(f"  ✅ Created PO: {data['po_number']}")
        print(f"     PO ID: {data['po_id']}")
        print(f"     From PR: {pr['pr_number']}")
        return data
    else:
        print(f"  ❌ Failed: {response.status_code}")
        print(f"     {response.text[:300]}")
        return None


def send_po(token, po_id, po_number):
    """Send PO to vendor"""
    print("\n  Sending PO to vendor...")

    response, error = api_request("POST", f"purchase-orders/{po_id}/send", token)
    if response and response.status_code == 200:
        print(f"  ✅ PO {po_number} sent to vendor")
        return True
    else:
        print(f"  ⚠️ Send failed: {response.status_code if response else error}")
        return False


def acknowledge_po(token, po_id, po_number):
    """Mark PO as acknowledged by vendor"""
    print("  Acknowledging PO (vendor confirmed)...")

    response, error = api_request("POST", f"purchase-orders/{po_id}/acknowledge", token)
    if response and response.status_code == 200:
        print(f"  ✅ PO {po_number} acknowledged")
        return True
    else:
        print(f"  ⚠️ Acknowledge failed: {response.status_code if response else error}")
        return False


def create_invoice(token, vendor, po_id):
    """Create Invoice (manual document) linked to PO"""
    print("\n" + "=" * 60)
    print("STEP 4: CREATE INVOICE")
    print("=" * 60)

    # Build line items for invoice
    line_items = []
    for item in INVOICE_DATA["line_items"]:
        discounted_price = item["unit_price"] * (1 - item["discount_pct"] / 100)
        total = item["quantity"] * discounted_price
        line_items.append({
            "item_number": item["item_number"],
            "description": item["description"],
            "quantity": item["quantity"],
            "unit": "EA",
            "unit_price": discounted_price,
            "total_price": total
        })

    invoice_data = {
        "document_type": "invoice",
        "invoice_category": "spare_parts",
        "document_number": INVOICE_DATA["invoice_number"],
        "document_date": INVOICE_DATA["invoice_date"],
        "due_date": (datetime.strptime(INVOICE_DATA["invoice_date"], "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d"),
        "currency": INVOICE_DATA["currency"],
        "subtotal": INVOICE_DATA["totals"]["net_before_vat"],
        "tax_amount": INVOICE_DATA["totals"]["vat_11_pct"],
        "total_amount": INVOICE_DATA["totals"]["net_after_vat"],
        "line_items": line_items,
        "notes": f"Delivery Note: {INVOICE_DATA['delivery_note']}\nVAT #: {INVOICE_DATA['vat_number']}\nCustomer: {INVOICE_DATA['customer']}"
    }

    # Use address_book_id for Address Book vendors
    if vendor.get("is_address_book"):
        invoice_data["address_book_id"] = vendor["id"]
    else:
        invoice_data["vendor_id"] = vendor["id"]

    response, error = api_request("POST", "images/manual", token, invoice_data)

    if error:
        print(f"  ❌ Error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        created_ids["invoices"].append(data["id"])
        print(f"  ✅ Created Invoice: {INVOICE_DATA['invoice_number']}")
        print(f"     Invoice ID: {data['id']}")
        print(f"     Supplier: {vendor['name']}")
        print(f"     Date: {INVOICE_DATA['invoice_date']}")
        print(f"     Subtotal: ${INVOICE_DATA['totals']['net_before_vat']:.2f}")
        print(f"     VAT (11%): ${INVOICE_DATA['totals']['vat_11_pct']:.2f}")
        print(f"     Total: ${INVOICE_DATA['totals']['net_after_vat']:.2f}")

        # Link invoice to PO
        print("\n  Linking invoice to PO...")
        link_response, link_error = api_request(
            "POST",
            f"purchase-orders/{po_id}/link-invoice",
            token,
            {"invoice_id": data["id"], "notes": "Linked from procurement flow test"}
        )
        if link_response and link_response.status_code in [200, 201]:
            print(f"  ✅ Invoice linked to PO")
        else:
            print(f"  ⚠️ Could not link invoice: {link_response.status_code if link_response else link_error}")

        return data
    else:
        print(f"  ❌ Failed: {response.status_code}")
        print(f"     {response.text[:300]}")
        return None


def get_warehouse(token):
    """Get default warehouse for receiving"""
    response, error = api_request("GET", "warehouses", token, {"limit": 1})
    if response and response.status_code == 200:
        data = response.json()
        warehouses = data.get("warehouses", data) if isinstance(data, dict) else data
        if warehouses and len(warehouses) > 0:
            return warehouses[0]
    return None


def create_goods_receipt(token, po_id, po_number):
    """Create Goods Receipt Note (GRN)"""
    print("\n" + "=" * 60)
    print("STEP 5: CREATE GOODS RECEIPT (GRN)")
    print("=" * 60)

    # Get PO with lines
    response, error = api_request("GET", f"purchase-orders/{po_id}", token)
    if not response or response.status_code != 200:
        print(f"  ❌ Could not get PO details: {error}")
        return None

    po = response.json()

    # Get warehouse
    warehouse = get_warehouse(token)
    warehouse_id = warehouse["id"] if warehouse else None

    if warehouse:
        print(f"  Using warehouse: {warehouse.get('name')} (ID: {warehouse_id})")
    else:
        print("  ⚠️ No warehouse found, proceeding without warehouse assignment")

    # Build GRN lines
    grn_lines = []
    for po_line in po.get("lines", []):
        grn_lines.append({
            "po_line_id": po_line["id"],
            "quantity_received": float(po_line["quantity_ordered"]),
            "warehouse_id": warehouse_id,
            "notes": f"Received from {INVOICE_DATA['supplier']['name']}"
        })

    grn_data = {
        "purchase_order_id": po_id,
        "receipt_date": date.today().isoformat(),
        "warehouse_id": warehouse_id,
        "supplier_delivery_note": INVOICE_DATA["delivery_note"],
        "carrier": "Direct from supplier",
        "inspection_required": False,
        "notes": f"Goods received for Invoice {INVOICE_DATA['invoice_number']}",
        "lines": grn_lines
    }

    response, error = api_request("POST", "goods-receipts", token, grn_data)

    if error:
        print(f"  ❌ Error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        grn_id = data.get("id")
        grn_number = data.get("grn_number")
        created_ids["goods_receipts"].append(grn_id)

        print(f"  ✅ Created GRN: {grn_number}")
        print(f"     GRN ID: {grn_id}")
        print(f"     Status: {data.get('status')}")
        print(f"     Lines: {len(grn_lines)} items")
        print(f"     Total: ${data.get('total_amount', 0):.2f}")

        return data
    else:
        print(f"  ❌ Failed: {response.status_code}")
        print(f"     {response.text[:300]}")
        return None


def post_goods_receipt(token, grn_id, grn_number):
    """Post GRN to finalize receiving and update inventory"""
    print("\n  Posting GRN (finalizing receipt)...")

    response, error = api_request("POST", f"goods-receipts/{grn_id}/post", token)

    if response and response.status_code == 200:
        data = response.json()
        print(f"  ✅ GRN {grn_number} posted successfully!")
        print(f"     Status: {data.get('status')}")
        if data.get("journal_entry_id"):
            print(f"     Journal Entry: {data.get('journal_entry_id')}")
        return True
    else:
        print(f"  ⚠️ Post failed: {response.status_code if response else error}")
        if response:
            print(f"     {response.text[:200]}")
        return False


def print_summary(vendor, pr, po, invoice, grn):
    """Print procurement flow summary"""
    print("\n" + "=" * 60)
    print("PROCUREMENT FLOW SUMMARY")
    print("=" * 60)

    print(f"""
    VENDOR:
    └── Name: {vendor['name'] if vendor else 'N/A'}
    └── ID: {vendor['id'] if vendor else 'N/A'}
    └── Source: {'Address Book' if vendor and vendor.get('is_address_book') else 'Legacy Vendors'}

    PURCHASE REQUEST (PR):
    └── Number: {pr['pr_number'] if pr else 'N/A'}
    └── Status: {pr.get('status', 'N/A') if pr else 'N/A'}

    PURCHASE ORDER (PO):
    └── Number: {po['po_number'] if po else 'N/A'}
    └── Status: Sent/Acknowledged

    INVOICE:
    └── Number: {INVOICE_DATA['invoice_number']}
    └── ID: {invoice['id'] if invoice else 'N/A'}
    └── Total: ${INVOICE_DATA['totals']['net_after_vat']:.2f}

    GOODS RECEIPT (GRN):
    └── Number: {grn['grn_number'] if grn else 'N/A'}
    └── Status: {grn.get('status', 'N/A') if grn else 'N/A'}
    └── Items Received: {len(grn.get('lines', [])) if grn else 0}

    LINE ITEMS ({len(INVOICE_DATA['line_items'])} items):
    """)

    for i, item in enumerate(INVOICE_DATA['line_items'], 1):
        discounted = item['unit_price'] * (1 - item['discount_pct']/100)
        total = item['quantity'] * discounted
        print(f"    {i}. {item['item_number']}: {item['description']}")
        print(f"       Qty: {item['quantity']} x ${discounted:.3f} = ${total:.2f}")

    print(f"""
    TOTALS:
    └── Subtotal: ${INVOICE_DATA['totals']['net_before_vat']:.2f}
    └── VAT (11%): ${INVOICE_DATA['totals']['vat_11_pct']:.2f}
    └── Total: ${INVOICE_DATA['totals']['net_after_vat']:.2f}
    """)


def main():
    print("\n" + "=" * 60)
    print("MRAD ELECTRIC INVOICE - PROCUREMENT FLOW")
    print("Invoice: " + INVOICE_DATA["invoice_number"])
    print("=" * 60)

    # Step 0: Authenticate
    token = authenticate()
    if not token:
        print("\n❌ Cannot proceed without authentication")
        sys.exit(1)

    # Step 1: Setup vendor
    vendor = setup_vendor(token)
    if not vendor:
        print("\n❌ Cannot proceed without vendor")
        sys.exit(1)

    # Get legacy vendor ID for PO (required by current API)
    legacy_vendor_id = get_or_create_vendor_legacy(token)
    if not legacy_vendor_id:
        print("\n❌ Cannot proceed without legacy vendor for PO")
        sys.exit(1)

    # Step 2: Create PR
    pr = create_purchase_request(token, legacy_vendor_id)
    if not pr:
        print("\n❌ Cannot proceed without PR")
        sys.exit(1)

    # Submit and approve PR
    if not submit_and_approve_pr(token, pr["id"], pr["pr_number"]):
        print("\n⚠️ PR not approved, but continuing...")

    # Step 3: Convert PR to PO
    po_result = convert_pr_to_po(token, pr["id"], legacy_vendor_id)
    if not po_result:
        print("\n❌ Cannot proceed without PO")
        sys.exit(1)

    po_id = po_result["po_id"]
    po_number = po_result["po_number"]

    # Send and acknowledge PO
    send_po(token, po_id, po_number)
    acknowledge_po(token, po_id, po_number)

    # Step 4: Create Invoice
    invoice = create_invoice(token, vendor, po_id)
    if not invoice:
        print("\n⚠️ Invoice creation failed, but continuing with GRN...")

    # Step 5: Create Goods Receipt
    grn = create_goods_receipt(token, po_id, po_number)
    if grn:
        # Post GRN
        post_goods_receipt(token, grn["id"], grn["grn_number"])

    # Print summary
    print_summary(vendor, pr, po_result, invoice, grn)

    print("\n" + "=" * 60)
    print("PROCUREMENT FLOW COMPLETED!")
    print("=" * 60)

    # Return success/failure
    success = all([vendor, pr, po_result, grn])
    print(f"\nResult: {'✅ SUCCESS' if success else '⚠️ PARTIAL SUCCESS'}")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
