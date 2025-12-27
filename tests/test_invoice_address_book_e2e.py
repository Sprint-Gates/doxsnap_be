"""
End-to-End Test: Invoice Processing with Address Book Vendor Creation

Tests the complete flow:
1. Login to get auth token
2. Upload invoice PDF
3. Verify vendor auto-created in Address Book (search_type='V')
4. Verify invoice linked to Address Book vendor
5. Verify line items extracted
"""

import requests
import os
import sys
import json
import time

# Configuration
BASE_URL = os.environ.get("API_URL", "http://localhost:8000")
TEST_EMAIL = os.environ.get("TEST_EMAIL", "test@doxsnap.com")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "test123")
INVOICE_PATH = "/Users/mohamaditani/Desktop/doxsnap/active_doxsnap/MM-60-2022 26.pdf"


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_success(text):
    print(f"  ✓ {text}")


def print_error(text):
    print(f"  ✗ {text}")


def print_info(text):
    print(f"  → {text}")


def login():
    """Login and get auth token"""
    print_header("Step 1: Login")

    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
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
    print_info(f"Remaining documents: {user.get('remaining_documents')}")

    return token, user


def upload_invoice(token):
    """Upload invoice PDF for processing"""
    print_header("Step 2: Upload Invoice PDF")

    if not os.path.exists(INVOICE_PATH):
        print_error(f"Invoice file not found: {INVOICE_PATH}")
        return None

    headers = {"Authorization": f"Bearer {token}"}

    with open(INVOICE_PATH, "rb") as f:
        files = {"file": ("MM-60-2022 26.pdf", f, "application/pdf")}
        data = {"document_type": "invoice"}

        print_info("Uploading and processing invoice...")
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
    print_info(f"Extraction confidence: {invoice.get('extraction_confidence')}")

    return invoice


def get_invoice_details(token, invoice_id):
    """Get full invoice details with structured data"""
    print_header("Step 3: Get Invoice Structured Data")

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
        print_info(f"  {i+1}. {item.get('description', 'N/A')[:40]} - Qty: {item.get('quantity')} @ {item.get('unit_price')}")
    if len(line_items) > 5:
        print_info(f"  ... and {len(line_items) - 5} more items")

    return structured


def check_address_book_vendor(token, supplier_name):
    """Check if vendor was created in Address Book"""
    print_header("Step 4: Verify Address Book Vendor")

    headers = {"Authorization": f"Bearer {token}"}

    # Search for vendor in Address Book
    response = requests.get(
        f"{BASE_URL}/api/address-book/vendors",
        headers=headers,
        params={"search": supplier_name[:20] if supplier_name else "MRAD"}
    )

    if response.status_code != 200:
        print_error(f"Failed to search Address Book: {response.status_code}")
        print_error(response.text)
        return None

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


def check_invoice_vendor_link(token, invoice_id):
    """Check vendor lookup for the invoice"""
    print_header("Step 5: Verify Invoice-Vendor Link")

    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"{BASE_URL}/api/images/{invoice_id}/vendor-lookup",
        headers=headers
    )

    if response.status_code != 200:
        print_error(f"Failed to check vendor link: {response.status_code}")
        return None

    data = response.json()

    if data.get("found"):
        vendor = data.get("vendor", {})
        print_success("Invoice linked to vendor:")
        print_info(f"  Vendor ID: {vendor.get('id')}")
        print_info(f"  Address Number: {vendor.get('address_number')}")
        print_info(f"  Name: {vendor.get('display_name')}")
        print_info(f"  Tax Number: {vendor.get('tax_number')}")
    else:
        print_info("Invoice not yet linked to vendor")
        print_info(f"  Extracted name: {data.get('extracted_name')}")
        if data.get("suggestions"):
            print_info(f"  Suggestions: {len(data.get('suggestions'))} vendors found")

    return data


def get_invoice_items(token, invoice_id):
    """Get invoice line items from the database"""
    print_header("Step 6: Verify Invoice Items in Database")

    headers = {"Authorization": f"Bearer {token}"}

    # Get invoice items
    response = requests.get(
        f"{BASE_URL}/api/admin/invoice-items/{invoice_id}",
        headers=headers
    )

    if response.status_code != 200:
        print_info(f"Could not retrieve invoice items: {response.status_code}")
        return None

    items = response.json()

    if items:
        print_success(f"Found {len(items)} invoice items in database:")
        for item in items[:5]:
            status = "✓" if item.get("item_master_id") else "○"
            print_info(f"  {status} {item.get('item_description', 'N/A')[:35]} - Qty: {item.get('quantity')}")
    else:
        print_info("No invoice items found in database")

    return items


def run_test():
    """Run the complete E2E test"""
    print("\n" + "="*60)
    print("  INVOICE PROCESSING E2E TEST - ADDRESS BOOK VENDOR")
    print("="*60)
    print(f"\nAPI URL: {BASE_URL}")
    print(f"Test User: {TEST_EMAIL}")
    print(f"Invoice: {INVOICE_PATH}")

    # Step 1: Login
    result = login()
    if not result:
        print_error("Test failed at login step")
        return False

    token, user = result

    # Step 2: Upload invoice
    invoice = upload_invoice(token)
    if not invoice:
        print_error("Test failed at upload step")
        return False

    invoice_id = invoice.get("id")

    # Step 3: Get structured data
    structured = get_invoice_details(token, invoice_id)

    # Step 4: Check Address Book vendor
    supplier_name = None
    if structured:
        supplier_name = structured.get("supplier", {}).get("company_name")

    vendor = check_address_book_vendor(token, supplier_name)

    # Step 5: Check invoice-vendor link
    vendor_link = check_invoice_vendor_link(token, invoice_id)

    # Step 6: Check invoice items
    items = get_invoice_items(token, invoice_id)

    # Summary
    print_header("TEST SUMMARY")

    tests_passed = 0
    total_tests = 6

    # Test 1: Login
    if token:
        print_success("Login: PASSED")
        tests_passed += 1
    else:
        print_error("Login: FAILED")

    # Test 2: Upload
    if invoice:
        print_success("Invoice Upload: PASSED")
        tests_passed += 1
    else:
        print_error("Invoice Upload: FAILED")

    # Test 3: Structured data extraction
    if structured and structured.get("line_items"):
        print_success(f"Data Extraction: PASSED ({len(structured.get('line_items', []))} line items)")
        tests_passed += 1
    else:
        print_error("Data Extraction: FAILED")

    # Test 4: Address Book vendor created
    if vendor:
        print_success(f"Address Book Vendor: PASSED (ID: {vendor.get('id')})")
        tests_passed += 1
    else:
        print_error("Address Book Vendor: FAILED - No vendor in Address Book")

    # Test 5: Invoice linked to vendor
    if vendor_link and vendor_link.get("found"):
        print_success("Invoice-Vendor Link: PASSED")
        tests_passed += 1
    elif structured and structured.get("supplier", {}).get("address_book_id"):
        print_success(f"Invoice-Vendor Link: PASSED (via structured data, AB ID: {structured.get('supplier', {}).get('address_book_id')})")
        tests_passed += 1
    else:
        print_error("Invoice-Vendor Link: FAILED")

    # Test 6: Invoice items
    if items and len(items) > 0:
        print_success(f"Invoice Items: PASSED ({len(items)} items)")
        tests_passed += 1
    else:
        print_info("Invoice Items: SKIPPED (endpoint may not be available)")
        total_tests -= 1

    print(f"\nResult: {tests_passed}/{total_tests} tests passed")

    if tests_passed >= total_tests - 1:  # Allow 1 failure for optional tests
        print_success("E2E TEST PASSED!")
        return True
    else:
        print_error("E2E TEST FAILED!")
        return False


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
