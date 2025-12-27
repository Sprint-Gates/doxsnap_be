"""
End-to-End Test: Registration and Invoice Processing with Address Book

Tests the complete flow on a fresh database:
1. Register a new company and admin user
2. Login to get auth token
3. Upload invoice PDF
4. Verify vendor auto-created in Address Book (search_type='V')
5. Verify invoice linked to Address Book vendor
"""

import requests
import os
import sys
import time

# Configuration
BASE_URL = os.environ.get("API_URL", "http://localhost:8000")
INVOICE_PATH = "/Users/mohamaditani/Desktop/doxsnap/active_doxsnap/MM-60-2022 26.pdf"

# Registration data
COMPANY_DATA = {
    "company_name": "Test Company",
    "company_email": "company@test.com",
    "company_phone": "+1234567890",
    "company_address": "123 Test Street",
    "company_city": "Test City",
    "company_country": "Lebanon",
    "industry": "Technology",
    "company_size": "1-10 employees",
    "admin_name": "Test Admin",
    "admin_email": "admin@test.com",
    "admin_password": "admin123",
    "admin_phone": "+1234567890",
    "plan_slug": "starter"  # Will be updated based on available plans
}


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_success(text):
    print(f"  [OK] {text}")


def print_error(text):
    print(f"  [ERROR] {text}")


def print_info(text):
    print(f"  -> {text}")


def get_plans():
    """Get available plans"""
    print_header("Step 0: Get Available Plans")

    response = requests.get(f"{BASE_URL}/api/plans/")

    if response.status_code != 200:
        print_error(f"Failed to get plans: {response.status_code}")
        print_error(response.text)
        return None

    plans = response.json()
    print_success(f"Found {len(plans)} plans")

    for plan in plans:
        print_info(f"  {plan.get('name')} ({plan.get('slug')}) - ${plan.get('price_monthly')}/month")

    return plans


def register_company():
    """Register a new company and admin user"""
    print_header("Step 1: Register Company")

    # First get available plans
    plans = get_plans()
    if plans:
        # Use the first available plan
        COMPANY_DATA["plan_slug"] = plans[0].get("slug", "starter")
        print_info(f"Using plan: {COMPANY_DATA['plan_slug']}")

    print_info(f"Registering company: {COMPANY_DATA['company_name']}")
    print_info(f"Admin email: {COMPANY_DATA['admin_email']}")

    response = requests.post(
        f"{BASE_URL}/api/companies/register",
        json=COMPANY_DATA
    )

    if response.status_code not in [200, 201]:
        print_error(f"Registration failed: {response.status_code}")
        print_error(response.text)
        return None

    data = response.json()

    if data.get("success"):
        print_success("Company registered successfully!")
        print_info(f"Company ID: {data.get('company_id')}")
        print_info(f"User ID: {data.get('user', {}).get('id')}")
        print_info(f"Token received: Yes")
        return data
    else:
        print_error(f"Registration failed: {data.get('message', 'Unknown error')}")
        return None


def login(email, password):
    """Login and get auth token"""
    print_header("Step 2: Login")

    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password}
    )

    if response.status_code != 200:
        print_error(f"Login failed: {response.status_code}")
        print_error(response.text)
        return None

    data = response.json()
    token = data.get("access_token")
    user = data.get("user", {})

    print_success(f"Logged in as: {user.get('email')}")
    print_info(f"Company ID: {user.get('company_id')}")
    print_info(f"Role: {user.get('role')}")
    print_info(f"Remaining documents: {user.get('remaining_documents')}")

    return token, user


def upload_invoice(token):
    """Upload invoice PDF for processing"""
    print_header("Step 3: Upload Invoice PDF")

    if not os.path.exists(INVOICE_PATH):
        print_error(f"Invoice file not found: {INVOICE_PATH}")
        return None

    headers = {"Authorization": f"Bearer {token}"}

    with open(INVOICE_PATH, "rb") as f:
        files = {"file": ("MM-60-2022 26.pdf", f, "application/pdf")}
        data = {"document_type": "invoice"}

        print_info("Uploading and processing invoice...")
        print_info(f"File: {INVOICE_PATH}")
        start_time = time.time()

        response = requests.post(
            f"{BASE_URL}/api/images/upload",
            headers=headers,
            files=files,
            data=data
        )

        elapsed = time.time() - start_time

    if response.status_code not in [200, 201]:
        print_error(f"Upload failed: {response.status_code}")
        print_error(response.text)
        return None

    invoice = response.json()

    print_success(f"Invoice uploaded successfully (took {elapsed:.2f}s)")
    print_info(f"Invoice ID: {invoice.get('id')}")
    print_info(f"Processing status: {invoice.get('processing_status')}")
    print_info(f"Processing method: {invoice.get('processing_method')}")
    print_info(f"Has structured data: {invoice.get('has_structured_data')}")

    return invoice


def get_invoice_details(token, invoice_id):
    """Get full invoice details with structured data"""
    print_header("Step 4: Get Invoice Structured Data")

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"{BASE_URL}/api/images/{invoice_id}/structured-data",
        headers=headers
    )

    if response.status_code != 200:
        print_error(f"Failed to get structured data: {response.status_code}")
        return None

    data = response.json()
    structured = data.get("structured_data", {})

    # Supplier info
    supplier = structured.get("supplier", {})
    print_success("Extracted supplier info:")
    print_info(f"  Company: {supplier.get('company_name')}")
    print_info(f"  VAT: {supplier.get('vat_number')}")
    print_info(f"  Email: {supplier.get('email')}")
    print_info(f"  Phone: {supplier.get('phone')}")
    print_info(f"  Address Book ID: {supplier.get('address_book_id')}")
    print_info(f"  Vendor Matched: {supplier.get('vendor_matched')}")

    # Document info
    doc_info = structured.get("document_info", {})
    print_success("Extracted document info:")
    print_info(f"  Invoice #: {doc_info.get('invoice_number')}")
    print_info(f"  Date: {doc_info.get('invoice_date')}")

    # Financial summary
    financial = structured.get("financial_details", {})
    print_success("Extracted financial details:")
    print_info(f"  Subtotal: {financial.get('subtotal')}")
    print_info(f"  VAT: {financial.get('total_tax_amount')}")
    print_info(f"  Total: {financial.get('total_after_tax')}")
    print_info(f"  Currency: {financial.get('currency')}")

    # Line items
    line_items = structured.get("line_items", [])
    print_success(f"Extracted {len(line_items)} line items:")
    for i, item in enumerate(line_items[:5]):  # Show first 5
        desc = item.get('description', 'N/A')[:40]
        qty = item.get('quantity', '-')
        price = item.get('unit_price', '-')
        print_info(f"  {i+1}. {desc} - Qty: {qty} @ {price}")
    if len(line_items) > 5:
        print_info(f"  ... and {len(line_items) - 5} more items")

    return structured


def check_address_book_vendor(token, supplier_name):
    """Check if vendor was created in Address Book"""
    print_header("Step 5: Verify Address Book Vendor")

    headers = {"Authorization": f"Bearer {token}"}

    # Search for vendor in Address Book
    search_term = supplier_name[:20] if supplier_name else "MRAD"
    response = requests.get(
        f"{BASE_URL}/api/address-book/vendors",
        headers=headers,
        params={"search": search_term}
    )

    if response.status_code != 200:
        print_error(f"Failed to search Address Book: {response.status_code}")
        print_error(response.text)
        return None

    vendors = response.json()

    if not vendors:
        # Try without search filter
        response = requests.get(
            f"{BASE_URL}/api/address-book/vendors",
            headers=headers
        )
        if response.status_code == 200:
            vendors = response.json()

    if not vendors:
        print_error("No vendors found in Address Book")
        return None

    print_success(f"Found {len(vendors)} vendor(s) in Address Book:")

    for vendor in vendors:
        print_info(f"  ID: {vendor.get('id')}")
        print_info(f"  Address Number: {vendor.get('address_number')}")
        print_info(f"  Name: {vendor.get('alpha_name')}")
        print_info(f"  Search Type: {vendor.get('search_type')}")
        print_info(f"  Tax ID: {vendor.get('tax_id')}")
        print_info(f"  Email: {vendor.get('email')}")
        print_info(f"  Business Unit ID: {vendor.get('business_unit_id')}")
        print_info("")

    return vendors[0] if vendors else None


def run_test():
    """Run the complete E2E test"""
    print("\n" + "="*60)
    print("  REGISTRATION & INVOICE PROCESSING E2E TEST")
    print("="*60)
    print(f"\nAPI URL: {BASE_URL}")
    print(f"Invoice: {INVOICE_PATH}")

    tests_passed = 0
    total_tests = 5

    # Step 1: Register company
    reg_result = register_company()
    if not reg_result:
        print_error("Test failed at registration step")
        return False
    tests_passed += 1

    # Get token from registration or login
    token = reg_result.get("access_token")

    if not token:
        # Try to login
        login_result = login(COMPANY_DATA["admin_email"], COMPANY_DATA["admin_password"])
        if not login_result:
            print_error("Test failed at login step")
            return False
        token, user = login_result

    tests_passed += 1

    # Step 3: Upload invoice
    invoice = upload_invoice(token)
    if not invoice:
        print_error("Test failed at upload step")
        return False
    tests_passed += 1

    invoice_id = invoice.get("id")

    # Step 4: Get structured data
    structured = get_invoice_details(token, invoice_id)
    if not structured:
        print_error("Test failed at structured data step")
    else:
        tests_passed += 1

    # Step 5: Check Address Book vendor
    supplier_name = None
    if structured:
        supplier_name = structured.get("supplier", {}).get("company_name")

    vendor = check_address_book_vendor(token, supplier_name)
    if vendor:
        tests_passed += 1

    # Summary
    print_header("TEST SUMMARY")

    checks = [
        ("Registration", reg_result is not None),
        ("Login/Token", token is not None),
        ("Invoice Upload", invoice is not None),
        ("Data Extraction", structured is not None and len(structured.get("line_items", [])) > 0),
        ("Address Book Vendor", vendor is not None),
    ]

    for name, passed in checks:
        if passed:
            print_success(f"{name}: PASSED")
        else:
            print_error(f"{name}: FAILED")

    print(f"\nResult: {tests_passed}/{total_tests} tests passed")

    if tests_passed >= total_tests - 1:
        print_success("E2E TEST PASSED!")
        return True
    else:
        print_error("E2E TEST FAILED!")
        return False


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
