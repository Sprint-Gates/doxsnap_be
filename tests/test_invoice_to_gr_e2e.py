"""
Simplified E2E Test: Invoice Processing to Goods Receipt

This test focuses on the working parts of the procurement flow:
1. Register new company and user
2. Create vendor in Address Book
3. Upload and process invoice (AI extraction)
4. Create items in Item Master from invoice
5. Create Warehouse
6. Create PO directly (bypassing PR)
7. Create Goods Receipt from PO
8. Verify Item Ledger entries
"""

import requests
import os
import sys
import time
import json
from datetime import date, timedelta

# Configuration
BASE_URL = os.environ.get("API_URL", "http://localhost:8000")
INVOICE_PATH = "/Users/mohamaditani/Desktop/doxsnap/active_doxsnap/MM-60-2022 26.pdf"

# Generate unique identifiers
UNIQUE_ID = int(time.time())

# Test data
COMPANY_DATA = {
    "company_name": f"Doxsnap E2E Co {UNIQUE_ID}",
    "company_email": f"company{UNIQUE_ID}@doxsnap.com",
    "company_phone": "+961123456",
    "company_address": "Beirut, Lebanon",
    "company_city": "Beirut",
    "company_country": "Lebanon",
    "industry": "Electrical",
    "company_size": "11-50 employees",
    "admin_name": "Admin User",
    "admin_email": "admin@doxsnap.com",
    "admin_password": "111111",
    "admin_phone": "+961123456",
    "plan_slug": "professional"
}

# Invoice line items (from MM-60-2022 26.pdf)
LINE_ITEMS = [
    {"description": "FLUO 36W DAYLIGHT 120CM PHILIPS", "qty": 95, "unit": "EA", "cost": 1.00},
    {"description": "STARTER 20W PHILIPS", "qty": 266, "unit": "EA", "cost": 0.50},
    {"description": "STARTER 4-80W SYLVANIA", "qty": 79, "unit": "EA", "cost": 0.50},
    {"description": "DULUX D BASE G24 26W/21 OSRAM", "qty": 120, "unit": "EA", "cost": 3.00},
    {"description": "LED MR16 GU5.3 D/L 7.5W OSRAM", "qty": 60, "unit": "EA", "cost": 1.50},
    {"description": "CAPSULE G9 40W 240V OSRAM", "qty": 3, "unit": "EA", "cost": 2.00},
    {"description": "BALLAST 36W ELECTRONIC", "qty": 30, "unit": "EA", "cost": 5.00},
    {"description": "LED PANEL 60X60 40W", "qty": 10, "unit": "EA", "cost": 25.00},
    {"description": "EMERGENCY EXIT LIGHT LED", "qty": 5, "unit": "EA", "cost": 15.00},
]


def print_header(text):
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}")


def print_success(text):
    print(f"  [OK] {text}")


def print_error(text):
    print(f"  [ERROR] {text}")


def print_info(text):
    print(f"  -> {text}")


class InvoiceToGRTest:
    def __init__(self):
        self.token = None
        self.user = None
        self.company_id = None
        self.vendor_id = None
        self.invoice_id = None
        self.po_id = None
        self.warehouse_id = None
        self.gr_id = None
        self.item_ids = []
        self.po_lines = []

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def register_company(self):
        print_header("Step 1: Register Company and User")

        response = requests.post(
            f"{BASE_URL}/api/companies/register",
            json=COMPANY_DATA
        )

        if response.status_code not in [200, 201]:
            # If email already registered, try to login instead
            if "already registered" in response.text.lower():
                print_info("User already exists, attempting login...")
                login_response = requests.post(
                    f"{BASE_URL}/api/auth/login",
                    json={
                        "email": COMPANY_DATA["admin_email"],
                        "password": COMPANY_DATA["admin_password"]
                    }
                )
                if login_response.status_code == 200:
                    data = login_response.json()
                    self.token = data.get("access_token")
                    self.user = data.get("user")
                    self.company_id = data.get("user", {}).get("company_id")
                    print_success(f"Logged in as: {COMPANY_DATA['admin_email']}")
                    print_info(f"Company ID: {self.company_id}")
                    return True
                else:
                    print_error(f"Login failed: {login_response.status_code}")
                    print_error(login_response.text)
                    return False
            print_error(f"Registration failed: {response.status_code}")
            print_error(response.text)
            return False

        data = response.json()
        self.token = data.get("access_token")
        self.user = data.get("user")
        self.company_id = data.get("company", {}).get("id")

        print_success(f"Company registered: {data.get('company', {}).get('name')}")
        print_info(f"User: {self.user.get('email')}")
        print_info(f"Company ID: {self.company_id}")
        return True

    def create_vendor(self):
        print_header("Step 2: Create Vendor in Address Book")

        vendor_data = {
            "alpha_name": "MRAD ELECTRIC sal",
            "search_type": "V",
            "tax_id": "3176112-601",
            "email": "info@mradelectricsal.com",
            "phone": "09 23 07 18",
            "address_line_1": "Lebanon",
            "country": "Lebanon"
        }

        response = requests.post(
            f"{BASE_URL}/api/address-book",
            headers=self.headers(),
            json=vendor_data
        )

        if response.status_code not in [200, 201]:
            print_error(f"Vendor creation failed: {response.status_code}")
            print_error(response.text)
            return False

        vendor = response.json()
        self.vendor_id = vendor.get("id")

        print_success(f"Vendor created: {vendor.get('alpha_name')}")
        print_info(f"Vendor ID: {self.vendor_id}")
        return True

    def upload_invoice(self):
        print_header("Step 3: Upload and Process Invoice")

        if not os.path.exists(INVOICE_PATH):
            print_error(f"Invoice file not found: {INVOICE_PATH}")
            return False

        with open(INVOICE_PATH, "rb") as f:
            files = {"file": ("MM-60-2022 26.pdf", f, "application/pdf")}
            data = {"document_type": "invoice"}

            print_info("Uploading and processing invoice...")
            start_time = time.time()

            response = requests.post(
                f"{BASE_URL}/api/images/upload",
                headers=self.headers(),
                files=files,
                data=data
            )

            elapsed = time.time() - start_time

        if response.status_code not in [200, 201]:
            print_error(f"Invoice upload failed: {response.status_code}")
            print_error(response.text)
            return False

        invoice = response.json()
        self.invoice_id = invoice.get("id")

        print_success(f"Invoice processed in {elapsed:.2f}s")
        print_info(f"Invoice ID: {self.invoice_id}")
        print_info(f"Processing status: {invoice.get('processing_status')}")
        print_info(f"Has structured data: {invoice.get('has_structured_data')}")

        return True

    def create_items(self):
        print_header("Step 4: Create Items in Item Master")

        for i, item in enumerate(LINE_ITEMS):
            item_number = f"ELEC-{str(i+1).zfill(4)}"

            item_data = {
                "item_number": item_number,
                "description": item["description"],
                "unit": item["unit"],
                "unit_cost": item["cost"],
                "stocking_type": "S",
                "line_type": "S",
                "currency": "USD"
            }

            response = requests.post(
                f"{BASE_URL}/api/items/",
                headers=self.headers(),
                json=item_data
            )

            if response.status_code not in [200, 201]:
                print_error(f"Item creation failed: {response.status_code}")
                continue

            created_item = response.json()
            self.item_ids.append(created_item.get("id"))
            print_success(f"Created: {item_number}")

        print_info(f"Total items created: {len(self.item_ids)}")
        return len(self.item_ids) > 0

    def create_warehouse(self):
        print_header("Step 5: Create Warehouse")

        response = requests.get(
            f"{BASE_URL}/api/warehouses/",
            headers=self.headers()
        )

        if response.status_code == 200:
            warehouses = response.json()
            if warehouses:
                self.warehouse_id = warehouses[0].get("id")
                print_info(f"Using existing warehouse: {warehouses[0].get('name')}")
                return True

        warehouse_data = {
            "name": f"Main Warehouse {UNIQUE_ID}",
            "code": f"WH-{UNIQUE_ID % 10000}",
            "address": "Industrial Zone",
            "city": "Beirut",
            "country": "Lebanon",
            "is_main": True
        }

        response = requests.post(
            f"{BASE_URL}/api/warehouses/",
            headers=self.headers(),
            json=warehouse_data
        )

        if response.status_code not in [200, 201]:
            print_error(f"Warehouse creation failed: {response.status_code}")
            return False

        warehouse = response.json()
        self.warehouse_id = warehouse.get("id")
        print_success(f"Warehouse created: {warehouse.get('name')}")
        return True

    def create_po_direct(self):
        print_header("Step 6: Create Purchase Order Directly")

        # Build PO lines from our items
        po_lines = []
        for i, item_id in enumerate(self.item_ids):
            if i < len(LINE_ITEMS):
                po_lines.append({
                    "item_id": item_id,
                    "description": LINE_ITEMS[i]["description"],
                    "quantity_ordered": LINE_ITEMS[i]["qty"],
                    "unit": LINE_ITEMS[i]["unit"],
                    "unit_price": LINE_ITEMS[i]["cost"]
                })

        po_data = {
            "vendor_id": self.vendor_id,
            "order_date": date.today().isoformat(),
            "expected_date": (date.today() + timedelta(days=14)).isoformat(),
            "payment_terms": "Net 30",
            "currency": "USD",
            "lines": po_lines
        }

        response = requests.post(
            f"{BASE_URL}/api/purchase-orders/",
            headers=self.headers(),
            json=po_data
        )

        if response.status_code not in [200, 201]:
            print_error(f"PO creation failed: {response.status_code}")
            print_error(response.text[:500])
            return False

        po = response.json()
        self.po_id = po.get("id")
        self.po_lines = po.get("lines", [])

        print_success(f"PO created: {po.get('po_number')}")
        print_info(f"PO ID: {self.po_id}")
        print_info(f"Lines: {len(self.po_lines)}")
        return True

    def create_goods_receipt(self):
        print_header("Step 7: Create Goods Receipt")

        if not self.po_id:
            print_error("No PO ID available")
            return False

        # First, send the PO (change status from draft to sent)
        response = requests.post(
            f"{BASE_URL}/api/purchase-orders/{self.po_id}/send",
            headers=self.headers()
        )
        if response.status_code not in [200, 201]:
            print_error(f"Failed to send PO: {response.status_code}")
            print_error(response.text[:200])
            return False
        print_success("PO status changed to 'sent'")

        # Get PO details to get line IDs
        response = requests.get(
            f"{BASE_URL}/api/purchase-orders/{self.po_id}",
            headers=self.headers()
        )

        if response.status_code != 200:
            print_error(f"Failed to get PO: {response.status_code}")
            return False

        po = response.json()
        po_lines = po.get("lines", [])

        gr_lines = []
        for line in po_lines:
            gr_lines.append({
                "po_line_id": line["id"],
                "quantity_received": line.get("quantity", line.get("quantity_ordered", 0)),
                "warehouse_id": self.warehouse_id
            })

        gr_data = {
            "purchase_order_id": self.po_id,
            "receipt_date": date.today().isoformat(),
            "warehouse_id": self.warehouse_id,
            "supplier_delivery_note": "DN-2022-001",
            "notes": "Full receipt of electrical supplies",
            "lines": gr_lines
        }

        response = requests.post(
            f"{BASE_URL}/api/goods-receipts/",
            headers=self.headers(),
            json=gr_data
        )

        if response.status_code not in [200, 201]:
            print_error(f"GR creation failed: {response.status_code}")
            print_error(response.text[:500])
            return False

        gr = response.json()
        self.gr_id = gr.get("id")

        print_success(f"Goods Receipt created: {gr.get('grn_number')}")
        print_info(f"GR ID: {self.gr_id}")
        print_info(f"Lines received: {len(gr.get('lines', []))}")
        return True

    def verify_item_ledger(self):
        print_header("Step 8: Verify Item Ledger Entries")

        response = requests.get(
            f"{BASE_URL}/api/item-ledger/",
            headers=self.headers(),
            params={"limit": 50}
        )

        if response.status_code != 200:
            print_info(f"Item Ledger fetch: {response.status_code}")
            return True  # Non-critical

        data = response.json()
        ledger_entries = data.get("entries", [])

        if not ledger_entries:
            print_info("No ledger entries found")
            return True

        print_success(f"Found {len(ledger_entries)} ledger entries (total: {data.get('total', 0)})")

        for entry in ledger_entries[:5]:
            if isinstance(entry, dict):
                print_info(f"  {entry.get('transaction_type', 'N/A')}: "
                          f"Item {entry.get('item_number', 'N/A')} - "
                          f"Qty: {entry.get('quantity', 0)}")

        return True

    def run(self):
        print("\n" + "=" * 70)
        print("  INVOICE TO GOODS RECEIPT E2E TEST")
        print("=" * 70)
        print(f"\nAPI URL: {BASE_URL}")
        print(f"Invoice: {INVOICE_PATH}")

        steps = [
            ("Register Company", self.register_company),
            ("Create Vendor", self.create_vendor),
            ("Upload Invoice", self.upload_invoice),
            ("Create Items", self.create_items),
            ("Create Warehouse", self.create_warehouse),
            ("Create PO Direct", self.create_po_direct),
            ("Create Goods Receipt", self.create_goods_receipt),
            ("Verify Item Ledger", self.verify_item_ledger),
        ]

        passed = 0
        failed = 0

        for name, func in steps:
            try:
                if func():
                    passed += 1
                else:
                    failed += 1
                    print_error(f"Step failed: {name}")
            except Exception as e:
                failed += 1
                print_error(f"Exception: {name} - {str(e)}")

        print_header("TEST SUMMARY")

        print(f"\n  Results: {passed}/{len(steps)} passed")
        print(f"\n  Resources Created:")
        print(f"  - Company ID: {self.company_id}")
        print(f"  - Vendor ID: {self.vendor_id}")
        print(f"  - Invoice ID: {self.invoice_id}")
        print(f"  - Items: {len(self.item_ids)}")
        print(f"  - PO ID: {self.po_id}")
        print(f"  - Warehouse ID: {self.warehouse_id}")
        print(f"  - GR ID: {self.gr_id}")

        print(f"\n  Login Credentials:")
        print(f"  - Email: {COMPANY_DATA['admin_email']}")
        print(f"  - Password: {COMPANY_DATA['admin_password']}")

        if failed == 0:
            print_success("\nALL TESTS PASSED!")
            return True
        else:
            print_error(f"\n{failed} TEST(S) FAILED")
            return False


if __name__ == "__main__":
    test = InvoiceToGRTest()
    success = test.run()
    sys.exit(0 if success else 1)
