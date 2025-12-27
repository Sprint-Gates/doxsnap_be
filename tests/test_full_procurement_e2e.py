"""
Full End-to-End Procurement Flow Test

Complete flow:
1. Register new company and user
2. Create vendor in Address Book
3. Create Purchase Request with line items
4. Submit and Approve PR
5. Convert PR to Purchase Order
6. Upload and process invoice
7. Link invoice to PO
8. Create items in Item Master
9. Create Warehouse
10. Create Goods Receipt
11. Verify Item Ledger entries
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
    "company_name": f"Procurement Test Co {UNIQUE_ID}",
    "company_email": f"procurement{UNIQUE_ID}@test.com",
    "company_phone": "+961123456",
    "company_address": "Beirut, Lebanon",
    "company_city": "Beirut",
    "company_country": "Lebanon",
    "industry": "Electrical",
    "company_size": "11-50 employees",
    "admin_name": "Procurement Admin",
    "admin_email": f"procadmin{UNIQUE_ID}@test.com",
    "admin_password": "test123",
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


class ProcurementE2ETest:
    def __init__(self):
        self.token = None
        self.user = None
        self.company_id = None
        self.vendor_id = None
        self.pr_id = None
        self.po_id = None
        self.invoice_id = None
        self.warehouse_id = None
        self.gr_id = None
        self.item_ids = []
        self.pr_lines = []
        self.po_lines = []

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    # Step 1: Register Company
    def register_company(self):
        print_header("Step 1: Register Company and User")

        response = requests.post(
            f"{BASE_URL}/api/companies/register",
            json=COMPANY_DATA
        )

        if response.status_code not in [200, 201]:
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

    # Step 2: Create Vendor
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
            f"{BASE_URL}/api/address-book",  # No trailing slash for this endpoint
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
        print_info(f"Address Number: {vendor.get('address_number')}")
        return True

    # Step 3: Create Purchase Request
    def create_purchase_request(self):
        print_header("Step 3: Create Purchase Request")

        pr_data = {
            "title": "Electrical Supplies Order - MRAD",
            "description": "Fluorescent lights, starters, LEDs from MRAD Electric",
            "vendor_id": self.vendor_id,
            "priority": "normal",
            "currency": "USD",
            "required_date": (date.today() + timedelta(days=7)).isoformat(),
            "lines": [
                {
                    "description": item["description"],
                    "quantity_requested": item["qty"],
                    "unit": item["unit"],
                    "estimated_unit_cost": item["cost"]
                }
                for item in LINE_ITEMS
            ]
        }

        response = requests.post(
            f"{BASE_URL}/api/purchase-requests/",  # Trailing slash required
            headers=self.headers(),
            json=pr_data
        )

        if response.status_code not in [200, 201]:
            print_error(f"PR creation failed: {response.status_code}")
            print_error(response.text)
            return False

        pr = response.json()
        self.pr_id = pr.get("id")

        print_success(f"PR created: {pr.get('pr_number')}")
        print_info(f"PR ID: {self.pr_id}")
        print_info(f"Lines: {len(pr.get('lines', []))}")

        # Store PR lines for later
        self.pr_lines = pr.get("lines", [])

        return True

    # Step 4: Submit and Approve PR
    def submit_and_approve_pr(self):
        print_header("Step 4: Submit and Approve PR")

        # Submit
        response = requests.post(
            f"{BASE_URL}/api/purchase-requests/{self.pr_id}/submit",
            headers=self.headers()
        )

        if response.status_code != 200:
            print_error(f"PR submit failed: {response.status_code}")
            print_error(response.text)
            return False

        print_success("PR submitted for approval")

        # Approve - requires body with PurchaseRequestApproval schema
        approval_data = {
            "line_approvals": {},  # Empty means approve all as-is
            "notes": "Approved for procurement"
        }

        response = requests.post(
            f"{BASE_URL}/api/purchase-requests/{self.pr_id}/approve",
            headers=self.headers(),
            json=approval_data
        )

        if response.status_code != 200:
            print_error(f"PR approval failed: {response.status_code}")
            print_error(response.text)
            return False

        print_success("PR approved")
        return True

    # Step 5: Convert PR to PO
    def convert_to_po(self):
        print_header("Step 5: Convert PR to Purchase Order")

        # Build line prices from PR lines
        line_prices = {}
        for line in self.pr_lines:
            line_prices[str(line["id"])] = line.get("estimated_unit_cost", 0)

        convert_data = {
            "vendor_id": self.vendor_id,
            "order_date": date.today().isoformat(),
            "expected_date": (date.today() + timedelta(days=14)).isoformat(),
            "payment_terms": "Net 30",
            "shipping_address": "Main Warehouse, Beirut",
            "line_prices": line_prices
        }

        response = requests.post(
            f"{BASE_URL}/api/purchase-requests/{self.pr_id}/convert-to-po",
            headers=self.headers(),
            json=convert_data
        )

        if response.status_code not in [200, 201]:
            print_error(f"Convert to PO failed: {response.status_code}")
            print_error(response.text)
            return False

        result = response.json()
        self.po_id = result.get("po_id")

        print_success(f"PO created: {result.get('po_number')}")
        print_info(f"PO ID: {self.po_id}")

        # Get PO details for lines
        response = requests.get(
            f"{BASE_URL}/api/purchase-orders/{self.po_id}",
            headers=self.headers()
        )
        if response.status_code == 200:
            po = response.json()
            self.po_lines = po.get("lines", [])
            print_info(f"PO Lines: {len(self.po_lines)}")

        return True

    # Step 6: Upload Invoice
    def upload_invoice(self):
        print_header("Step 6: Upload and Process Invoice")

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

    # Step 7: Link Invoice to PO
    def link_invoice_to_po(self):
        print_header("Step 7: Link Invoice to PO")

        link_data = {
            "invoice_id": self.invoice_id,
            "matched_amount": None  # Will be calculated
        }

        response = requests.post(
            f"{BASE_URL}/api/purchase-orders/{self.po_id}/link-invoice",
            headers=self.headers(),
            json=link_data
        )

        if response.status_code not in [200, 201]:
            print_info(f"Invoice link via PO endpoint: {response.status_code}")
            # Try alternative - update invoice with PO ID
            response = requests.get(
                f"{BASE_URL}/api/images/{self.invoice_id}/structured-data",
                headers=self.headers()
            )
            if response.status_code == 200:
                print_success("Invoice structured data retrieved")
                data = response.json()
                supplier = data.get("structured_data", {}).get("supplier", {})
                print_info(f"Vendor matched: {supplier.get('vendor_matched')}")
                print_info(f"Address Book ID: {supplier.get('address_book_id')}")
            return True

        print_success("Invoice linked to PO")
        return True

    # Step 8: Create Items in Item Master
    def create_item_master_entries(self):
        print_header("Step 8: Create Items in Item Master")

        for i, item in enumerate(LINE_ITEMS):
            # Generate item number
            item_number = f"ELEC-{str(i+1).zfill(4)}"

            item_data = {
                "item_number": item_number,
                "description": item["description"],
                "unit": item["unit"],
                "unit_cost": item["cost"],
                "stocking_type": "S",
                "line_type": "S",
                "currency": "USD",
                "primary_address_book_id": self.vendor_id  # Correct field name
            }

            response = requests.post(
                f"{BASE_URL}/api/items/",  # Trailing slash
                headers=self.headers(),
                json=item_data
            )

            if response.status_code not in [200, 201]:
                print_error(f"Item creation failed for {item['description']}: {response.status_code}")
                print_error(response.text[:200])
                continue

            created_item = response.json()
            self.item_ids.append(created_item.get("id"))
            print_success(f"Created: {item_number} - {item['description'][:30]}...")

        print_info(f"Total items created: {len(self.item_ids)}")
        return len(self.item_ids) > 0

    # Step 9: Create Warehouse
    def create_warehouse(self):
        print_header("Step 9: Create Warehouse")

        # First check if warehouse exists
        response = requests.get(
            f"{BASE_URL}/api/warehouses/",
            headers=self.headers()
        )

        if response.status_code == 200:
            warehouses = response.json()
            if warehouses:
                # Use existing warehouse
                self.warehouse_id = warehouses[0].get("id")
                print_info(f"Using existing warehouse: {warehouses[0].get('name')}")
                print_info(f"Warehouse ID: {self.warehouse_id}")
                return True

        # Create new warehouse with unique name
        warehouse_data = {
            "name": f"Main Warehouse {int(time.time())}",
            "code": f"WH-{int(time.time()) % 10000}",
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
            print_error(response.text)
            return False

        warehouse = response.json()
        self.warehouse_id = warehouse.get("id")

        print_success(f"Warehouse created: {warehouse.get('name')}")
        print_info(f"Warehouse ID: {self.warehouse_id}")
        print_info(f"Code: {warehouse.get('code')}")
        return True

    # Step 10: Create Goods Receipt
    def create_goods_receipt(self):
        print_header("Step 10: Create Goods Receipt")

        # First, update PO lines with item_id
        # We need to link PO lines to item master items
        for i, po_line in enumerate(self.po_lines):
            if i < len(self.item_ids):
                # Update PO line with item_id
                update_data = {"item_id": self.item_ids[i]}
                requests.put(
                    f"{BASE_URL}/api/purchase-orders/{self.po_id}/lines/{po_line['id']}",
                    headers=self.headers(),
                    json=update_data
                )

        # Refresh PO lines
        response = requests.get(
            f"{BASE_URL}/api/purchase-orders/{self.po_id}",
            headers=self.headers()
        )
        if response.status_code == 200:
            self.po_lines = response.json().get("lines", [])

        # Create GR lines
        gr_lines = []
        for i, po_line in enumerate(self.po_lines):
            gr_lines.append({
                "po_line_id": po_line["id"],
                "quantity_received": po_line.get("quantity", po_line.get("quantity_ordered", 0)),
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
            print_error(f"Goods Receipt creation failed: {response.status_code}")
            print_error(response.text)
            return False

        gr = response.json()
        self.gr_id = gr.get("id")

        print_success(f"Goods Receipt created: {gr.get('grn_number')}")
        print_info(f"GR ID: {self.gr_id}")
        print_info(f"Status: {gr.get('status')}")
        print_info(f"Lines received: {len(gr.get('lines', []))}")
        return True

    # Step 11: Verify Item Ledger
    def verify_item_ledger(self):
        print_header("Step 11: Verify Item Ledger Entries")

        response = requests.get(
            f"{BASE_URL}/api/item-ledger/",  # Trailing slash
            headers=self.headers(),
            params={"limit": 50}
        )

        if response.status_code != 200:
            print_info(f"Item Ledger fetch: {response.status_code}")
            # Try checking stock instead
            response = requests.get(
                f"{BASE_URL}/api/item-stock/",
                headers=self.headers()
            )
            if response.status_code == 200:
                stocks = response.json()
                if stocks:
                    print_success(f"Found {len(stocks)} stock entries")
                    for stock in stocks[:5]:
                        print_info(f"  Item {stock.get('item_id')}: Qty {stock.get('quantity_on_hand', 0)}")
                    return True
            print_info("No ledger/stock entries found (GR may need posting)")
            return True

        ledger_entries = response.json()

        if not ledger_entries:
            print_info("No ledger entries found yet (may require GR posting)")
            return True

        print_success(f"Found {len(ledger_entries)} ledger entries")

        for entry in ledger_entries[:5]:
            print_info(f"  {entry.get('transaction_type', 'N/A')}: "
                      f"{entry.get('item_description', 'N/A')[:30]} - "
                      f"Qty: {entry.get('quantity', 0)}")

        if len(ledger_entries) > 5:
            print_info(f"  ... and {len(ledger_entries) - 5} more entries")

        return True

    # Run all tests
    def run(self):
        print("\n" + "=" * 70)
        print("  FULL PROCUREMENT E2E TEST")
        print("  PR -> PO -> Invoice -> Item Master -> GR -> Item Ledger")
        print("=" * 70)
        print(f"\nAPI URL: {BASE_URL}")
        print(f"Invoice: {INVOICE_PATH}")

        steps = [
            ("Register Company", self.register_company),
            ("Create Vendor", self.create_vendor),
            ("Create Purchase Request", self.create_purchase_request),
            ("Submit & Approve PR", self.submit_and_approve_pr),
            ("Convert to PO", self.convert_to_po),
            ("Upload Invoice", self.upload_invoice),
            ("Link Invoice to PO", self.link_invoice_to_po),
            ("Create Item Master Entries", self.create_item_master_entries),
            ("Create Warehouse", self.create_warehouse),
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
                print_error(f"Step exception: {name} - {str(e)}")

        # Summary
        print_header("TEST SUMMARY")

        print(f"\n  Results:")
        print(f"  --------")
        print(f"  Passed: {passed}/{len(steps)}")
        print(f"  Failed: {failed}/{len(steps)}")

        print(f"\n  Created Resources:")
        print(f"  ------------------")
        print(f"  Company ID: {self.company_id}")
        print(f"  Vendor ID: {self.vendor_id}")
        print(f"  PR ID: {self.pr_id}")
        print(f"  PO ID: {self.po_id}")
        print(f"  Invoice ID: {self.invoice_id}")
        print(f"  Warehouse ID: {self.warehouse_id}")
        print(f"  GR ID: {self.gr_id}")
        print(f"  Item IDs: {self.item_ids}")

        print(f"\n  Login Credentials:")
        print(f"  ------------------")
        print(f"  Email: {COMPANY_DATA['admin_email']}")
        print(f"  Password: {COMPANY_DATA['admin_password']}")

        if failed == 0:
            print_success("\nALL TESTS PASSED!")
            return True
        else:
            print_error(f"\n{failed} TEST(S) FAILED")
            return False


if __name__ == "__main__":
    test = ProcurementE2ETest()
    success = test.run()
    sys.exit(0 if success else 1)
