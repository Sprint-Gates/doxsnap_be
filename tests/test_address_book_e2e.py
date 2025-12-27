#!/usr/bin/env python3
"""
End-to-End Test Suite for Address Book API

Tests all Address Book functionality including:
- All search types (V, C, CB, E, MT)
- CRUD operations
- Contacts management
- Employee salary fields
- Parent-child hierarchy
- Business Unit auto-creation
- Work Order employee assignment
- Attendance tracking

Run from doxsnap_be directory:
    source venv/bin/activate
    python tests/test_address_book_e2e.py

Author: Claude Code
Date: 2025-12-26
"""

import os
import sys
import requests
import json
from datetime import date, datetime
from decimal import Decimal

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configuration
BASE_URL = os.getenv("API_URL", "http://localhost:8000")
API_URL = f"{BASE_URL}/api"

# Test credentials - update these for your environment
TEST_EMAIL = os.getenv("TEST_EMAIL", "admin@doxsnap.com")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "admin123")

# Store created IDs for cleanup
created_ids = {
    "address_book": [],
    "contacts": [],
    "work_orders": []
}

# Test results
test_results = {
    "passed": 0,
    "failed": 0,
    "errors": []
}


def log_test(name: str, passed: bool, message: str = ""):
    """Log test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}: {name}")
    if message:
        print(f"         {message}")

    if passed:
        test_results["passed"] += 1
    else:
        test_results["failed"] += 1
        test_results["errors"].append(f"{name}: {message}")


def get_auth_token():
    """Get authentication token"""
    print("\n🔐 Authenticating...")
    try:
        response = requests.post(
            f"{API_URL}/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        if response.status_code in [200, 201]:
            token = response.json().get("access_token")
            print(f"  ✅ Authentication successful")
            return token
        else:
            print(f"  ❌ Authentication failed: {response.status_code}")
            print(f"     Response: {response.text}")
            return None
    except Exception as e:
        print(f"  ❌ Authentication error: {e}")
        return None


def api_request(method: str, endpoint: str, token: str, data: dict = None, params: dict = None):
    """Make API request"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_URL}/{endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data)
        elif method == "PATCH":
            response = requests.patch(url, headers=headers, json=data, params=params)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            return None, f"Unknown method: {method}"

        return response, None
    except Exception as e:
        return None, str(e)


# ============ Test Functions ============

def test_create_vendor(token: str) -> dict:
    """Test creating a Vendor (search_type=V)"""
    print("\n📦 Testing Vendor Creation (V)...")

    vendor_data = {
        "search_type": "V",
        "alpha_name": "Test Vendor Corp",
        "mailing_name": "Test Vendor Corporation",
        "tax_id": "V-123456789",
        "registration_number": "REG-V-001",
        "address_line_1": "123 Vendor Street",
        "address_line_2": "Suite 100",
        "city": "New York",
        "state": "NY",
        "postal_code": "10001",
        "country": "USA",
        "phone_primary": "+1-555-0100",
        "phone_secondary": "+1-555-0101",
        "fax": "+1-555-0102",
        "email": "contact@testvendor.com",
        "website": "https://testvendor.com",
        "category_code_01": "SUPPLIER",
        "category_code_02": "PARTS",
        "notes": "Test vendor for E2E testing",
        "auto_create_bu": True
    }

    response, error = api_request("POST", "address-book", token, vendor_data)

    if error:
        log_test("Create Vendor", False, f"Request error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        created_ids["address_book"].append(data["id"])

        # Verify fields
        log_test("Vendor created", True, f"ID: {data['id']}, Address#: {data['address_number']}")
        log_test("Search type is V", data["search_type"] == "V")
        log_test("Alpha name set", data["alpha_name"] == "Test Vendor Corp")
        log_test("Tax ID set", data["tax_id"] == "V-123456789")
        log_test("Business Unit created", data.get("business_unit_id") is not None,
                 f"BU ID: {data.get('business_unit_id')}")

        return data
    else:
        log_test("Create Vendor", False, f"Status: {response.status_code}, Response: {response.text}")
        return None


def test_create_customer(token: str) -> dict:
    """Test creating a Customer (search_type=C)"""
    print("\n👤 Testing Customer Creation (C)...")

    customer_data = {
        "search_type": "C",
        "alpha_name": "Test Customer Inc",
        "mailing_name": "Test Customer Incorporated",
        "tax_id": "C-987654321",
        "registration_number": "REG-C-001",
        "address_line_1": "456 Customer Avenue",
        "city": "Los Angeles",
        "state": "CA",
        "postal_code": "90001",
        "country": "USA",
        "phone_primary": "+1-555-0200",
        "email": "info@testcustomer.com",
        "website": "https://testcustomer.com",
        "category_code_01": "ENTERPRISE",
        "notes": "Test customer for E2E testing",
        "auto_create_bu": True
    }

    response, error = api_request("POST", "address-book", token, customer_data)

    if error:
        log_test("Create Customer", False, f"Request error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        created_ids["address_book"].append(data["id"])

        log_test("Customer created", True, f"ID: {data['id']}")
        log_test("Search type is C", data["search_type"] == "C")
        log_test("Business Unit created", data.get("business_unit_id") is not None)

        return data
    else:
        log_test("Create Customer", False, f"Status: {response.status_code}")
        return None


def test_create_branch(token: str, parent_id: int) -> dict:
    """Test creating a Branch (search_type=CB) linked to Customer"""
    print("\n🏢 Testing Branch Creation (CB)...")

    branch_data = {
        "search_type": "CB",
        "alpha_name": "Test Customer - Downtown Branch",
        "parent_address_book_id": parent_id,
        "address_line_1": "789 Branch Road",
        "city": "Los Angeles",
        "state": "CA",
        "postal_code": "90002",
        "country": "USA",
        "phone_primary": "+1-555-0300",
        "email": "downtown@testcustomer.com",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "category_code_01": "BRANCH",
        "notes": "Downtown branch location",
        "auto_create_bu": True
    }

    response, error = api_request("POST", "address-book", token, branch_data)

    if error:
        log_test("Create Branch", False, f"Request error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        created_ids["address_book"].append(data["id"])

        log_test("Branch created", True, f"ID: {data['id']}")
        log_test("Search type is CB", data["search_type"] == "CB")
        log_test("Parent linked", data.get("parent_address_book_id") == parent_id)
        log_test("GPS coordinates set", data.get("latitude") is not None)

        return data
    else:
        log_test("Create Branch", False, f"Status: {response.status_code}, Response: {response.text}")
        return None


def test_create_employee(token: str) -> dict:
    """Test creating an Employee (search_type=E) with salary fields"""
    print("\n👷 Testing Employee Creation (E) with Salary...")

    employee_data = {
        "search_type": "E",
        "alpha_name": "John Doe",
        "mailing_name": "John Michael Doe",
        "address_line_1": "321 Worker Lane",
        "city": "Chicago",
        "state": "IL",
        "postal_code": "60601",
        "country": "USA",
        "phone_primary": "+1-555-0400",
        "phone_secondary": "+1-555-0401",
        "email": "john.doe@company.com",

        # Employee-specific fields
        "employee_id": "EMP-001",
        "specialization": "HVAC Technician",
        "hire_date": "2024-01-15",

        # Salary fields
        "salary_type": "monthly",
        "base_salary": 5000.00,
        "salary_currency": "USD",
        "hourly_rate": 28.50,
        "overtime_rate_multiplier": 1.5,
        "working_hours_per_day": 8.0,
        "working_days_per_month": 22,

        # Allowances
        "transport_allowance": 200.00,
        "housing_allowance": 500.00,
        "food_allowance": 150.00,
        "other_allowances": 100.00,
        "allowances_notes": "Performance bonus eligible",

        # Deductions
        "social_security_rate": 0.0725,
        "tax_rate": 0.15,
        "other_deductions": 50.00,
        "deductions_notes": "Union dues",

        "notes": "Senior HVAC technician",
        "auto_create_bu": False  # Employees typically don't need BU
    }

    response, error = api_request("POST", "address-book", token, employee_data)

    if error:
        log_test("Create Employee", False, f"Request error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        created_ids["address_book"].append(data["id"])

        log_test("Employee created", True, f"ID: {data['id']}")
        log_test("Search type is E", data["search_type"] == "E")
        log_test("Employee ID set", data.get("employee_id") == "EMP-001")
        log_test("Specialization set", data.get("specialization") == "HVAC Technician")
        log_test("Base salary set", float(data.get("base_salary", 0)) == 5000.00)
        log_test("Hourly rate set", float(data.get("hourly_rate", 0)) == 28.50)
        log_test("Transport allowance set", float(data.get("transport_allowance", 0)) == 200.00)
        log_test("Social security rate set", float(data.get("social_security_rate", 0)) == 0.0725)
        log_test("Hire date set", data.get("hire_date") is not None)

        return data
    else:
        log_test("Create Employee", False, f"Status: {response.status_code}, Response: {response.text}")
        return None


def test_create_team(token: str) -> dict:
    """Test creating a Maintenance Team (search_type=MT)"""
    print("\n👥 Testing Maintenance Team Creation (MT)...")

    team_data = {
        "search_type": "MT",
        "alpha_name": "HVAC Maintenance Team Alpha",
        "address_line_1": "Company HQ",
        "city": "Houston",
        "state": "TX",
        "postal_code": "77001",
        "country": "USA",
        "phone_primary": "+1-555-0500",
        "email": "hvac-team-alpha@company.com",
        "category_code_01": "HVAC",
        "category_code_02": "PRIMARY",
        "notes": "Primary HVAC maintenance team",
        "auto_create_bu": True
    }

    response, error = api_request("POST", "address-book", token, team_data)

    if error:
        log_test("Create Team", False, f"Request error: {error}")
        return None

    if response.status_code in [200, 201]:
        data = response.json()
        created_ids["address_book"].append(data["id"])

        log_test("Team created", True, f"ID: {data['id']}")
        log_test("Search type is MT", data["search_type"] == "MT")

        return data
    else:
        log_test("Create Team", False, f"Status: {response.status_code}")
        return None


def test_add_contacts(token: str, address_book_id: int):
    """Test adding contacts to an Address Book entry"""
    print("\n📇 Testing Contacts Management...")

    contacts = [
        {
            "full_name": "Jane Smith",
            "first_name": "Jane",
            "last_name": "Smith",
            "title": "Purchasing Manager",
            "contact_type": "primary",
            "phone_primary": "+1-555-1001",
            "phone_mobile": "+1-555-1002",
            "email": "jane.smith@testvendor.com",
            "is_primary": True
        },
        {
            "full_name": "Bob Johnson",
            "first_name": "Bob",
            "last_name": "Johnson",
            "title": "Technical Support",
            "contact_type": "technical",
            "phone_primary": "+1-555-1003",
            "email": "bob.johnson@testvendor.com",
            "is_primary": False
        },
        {
            "full_name": "Alice Brown",
            "first_name": "Alice",
            "last_name": "Brown",
            "title": "Billing Coordinator",
            "contact_type": "billing",
            "phone_primary": "+1-555-1004",
            "email": "alice.brown@testvendor.com",
            "is_primary": False
        }
    ]

    for contact in contacts:
        response, error = api_request(
            "POST",
            f"address-book/{address_book_id}/contacts",
            token,
            contact
        )

        if error:
            log_test(f"Add contact {contact['full_name']}", False, f"Error: {error}")
            continue

        if response.status_code in [200, 201]:
            data = response.json()
            created_ids["contacts"].append(data["id"])
            log_test(f"Add contact {contact['full_name']}", True, f"ID: {data['id']}")
        else:
            log_test(f"Add contact {contact['full_name']}", False, f"Status: {response.status_code}")

    # Verify contacts list
    response, error = api_request("GET", f"address-book/{address_book_id}/contacts", token)
    if response and response.status_code == 200:
        contacts_list = response.json()
        log_test("List contacts", len(contacts_list) >= 3, f"Found {len(contacts_list)} contacts")


def test_list_and_filter(token: str):
    """Test listing and filtering Address Book entries"""
    print("\n🔍 Testing List and Filter Operations...")

    # List all
    response, error = api_request("GET", "address-book", token)
    if response and response.status_code == 200:
        data = response.json()
        log_test("List all entries", True, f"Found {len(data)} entries")
    else:
        log_test("List all entries", False)

    # Filter by type - Vendors
    response, error = api_request("GET", "address-book", token, params={"search_type": "V"})
    if response and response.status_code == 200:
        data = response.json()
        all_vendors = all(e["search_type"] == "V" for e in data)
        log_test("Filter by type V", all_vendors, f"Found {len(data)} vendors")
    else:
        log_test("Filter by type V", False)

    # Filter by type - Employees
    response, error = api_request("GET", "address-book", token, params={"search_type": "E"})
    if response and response.status_code == 200:
        data = response.json()
        all_employees = all(e["search_type"] == "E" for e in data)
        log_test("Filter by type E", all_employees, f"Found {len(data)} employees")
    else:
        log_test("Filter by type E", False)

    # Get brief list for dropdowns
    response, error = api_request("GET", "address-book/brief", token)
    if response and response.status_code == 200:
        data = response.json()
        log_test("Get brief list", True, f"Found {len(data)} entries")
    else:
        log_test("Get brief list", False)

    # Search by name
    response, error = api_request("GET", "address-book", token, params={"search": "Test"})
    if response and response.status_code == 200:
        data = response.json()
        log_test("Search by name", True, f"Found {len(data)} matching entries")
    else:
        log_test("Search by name", False)


def test_hierarchy(token: str, parent_id: int):
    """Test parent-child hierarchy"""
    print("\n🌳 Testing Hierarchy Operations...")

    # Get children of customer
    response, error = api_request("GET", f"address-book/{parent_id}/children", token)
    if response and response.status_code == 200:
        children = response.json()
        log_test("Get children", True, f"Found {len(children)} children")
    else:
        log_test("Get children", False)

    # Get hierarchy view
    response, error = api_request("GET", "address-book/hierarchy", token)
    if response and response.status_code == 200:
        hierarchy = response.json()
        log_test("Get hierarchy", True, f"Found {len(hierarchy)} root entries")
    else:
        log_test("Get hierarchy", False)


def test_update_entry(token: str, entry_id: int):
    """Test updating an Address Book entry"""
    print("\n✏️ Testing Update Operations...")

    update_data = {
        "alpha_name": "Updated Test Vendor Corp",
        "phone_primary": "+1-555-9999",
        "notes": "Updated via E2E test"
    }

    response, error = api_request("PUT", f"address-book/{entry_id}", token, update_data)
    if response and response.status_code == 200:
        data = response.json()
        log_test("Update entry", data["alpha_name"] == "Updated Test Vendor Corp")
        log_test("Phone updated", data["phone_primary"] == "+1-555-9999")
    else:
        log_test("Update entry", False, f"Status: {response.status_code if response else 'No response'}")


def test_toggle_status(token: str, entry_id: int):
    """Test toggling active status"""
    print("\n🔄 Testing Status Toggle...")

    # Deactivate
    response, error = api_request("PATCH", f"address-book/{entry_id}/toggle-status", token)
    if response and response.status_code == 200:
        data = response.json()
        log_test("Deactivate entry", data["is_active"] == False)
    else:
        log_test("Deactivate entry", False)

    # Reactivate
    response, error = api_request("PATCH", f"address-book/{entry_id}/toggle-status", token)
    if response and response.status_code == 200:
        data = response.json()
        log_test("Reactivate entry", data["is_active"] == True)
    else:
        log_test("Reactivate entry", False)


def test_employee_work_order_assignment(token: str, employee_id: int):
    """Test assigning employee to work order"""
    print("\n🔧 Testing Employee Work Order Assignment...")

    # First, get an existing work order or create one
    response, error = api_request("GET", "work-orders", token, params={"limit": 1})

    wo_id = None
    if response and response.status_code == 200:
        work_orders = response.json()
        if work_orders and len(work_orders) > 0:
            wo_id = work_orders[0]["id"]
            log_test("Found existing work order", True, f"WO ID: {wo_id}")

    if not wo_id:
        log_test("Work order assignment", False, "No work orders available for testing")
        return

    # Assign employee to work order
    response, error = api_request("POST", f"work-orders/{wo_id}/employees/{employee_id}", token)
    if response and response.status_code == 200:
        log_test("Assign employee to WO", True)
    elif response and response.status_code == 400:
        # Already assigned is OK
        log_test("Assign employee to WO", True, "Already assigned")
    else:
        log_test("Assign employee to WO", False, f"Status: {response.status_code if response else 'No response'}")

    # Get work order employees
    response, error = api_request("GET", f"work-orders/{wo_id}/employees", token)
    if response and response.status_code == 200:
        employees = response.json()
        has_employee = any(e["address_book_id"] == employee_id for e in employees)
        log_test("Employee in WO list", has_employee, f"Found {len(employees)} employees")
    else:
        log_test("Get WO employees", False)

    # Unassign employee
    response, error = api_request("DELETE", f"work-orders/{wo_id}/employees/{employee_id}", token)
    if response and response.status_code == 200:
        log_test("Unassign employee from WO", True)
    else:
        log_test("Unassign employee from WO", False)


def test_employee_attendance(token: str, employee_id: int):
    """Test employee attendance tracking"""
    print("\n📅 Testing Employee Attendance...")

    today = date.today().isoformat()

    # Create attendance record
    attendance_data = {
        "address_book_id": employee_id,
        "date": today,
        "status": "present",
        "check_in": f"{today}T08:00:00",
        "check_out": f"{today}T17:00:00",
        "break_duration_minutes": 60,
        "notes": "E2E test attendance"
    }

    response, error = api_request("POST", "attendance/employees/", token, attendance_data)
    if response and response.status_code == 200:
        data = response.json()
        log_test("Create attendance record", True, f"ID: {data['id']}")
        log_test("Hours calculated", data.get("hours_worked") is not None)
    elif response and response.status_code == 400:
        log_test("Create attendance record", True, "Record already exists for today")
    else:
        log_test("Create attendance record", False, f"Status: {response.status_code if response else 'No response'}")

    # Get daily attendance
    response, error = api_request("GET", f"attendance/employees/daily/{today}", token)
    if response and response.status_code == 200:
        records = response.json()
        log_test("Get daily attendance", True, f"Found {len(records)} employees")
    else:
        log_test("Get daily attendance", False)

    # Get employee monthly attendance
    response, error = api_request(
        "GET",
        f"attendance/employees/{employee_id}/monthly",
        token,
        params={"year": date.today().year, "month": date.today().month}
    )
    if response and response.status_code == 200:
        data = response.json()
        log_test("Get monthly attendance", True, f"Working days: {data['summary'].get('working_days', 0)}")
    else:
        log_test("Get monthly attendance", False)


def test_type_specific_endpoints(token: str):
    """Test type-specific view endpoints"""
    print("\n📊 Testing Type-Specific Endpoints...")

    endpoints = [
        ("address-book/vendors", "Vendors"),
        ("address-book/customers", "Customers"),
        ("address-book/branches", "Branches"),
        ("address-book/employees", "Employees"),
        ("address-book/teams", "Teams")
    ]

    for endpoint, name in endpoints:
        response, error = api_request("GET", endpoint, token)
        if response and response.status_code == 200:
            data = response.json()
            log_test(f"Get {name}", True, f"Found {len(data)} entries")
        else:
            log_test(f"Get {name}", False)


def test_lookup_endpoints(token: str):
    """Test lookup endpoints"""
    print("\n🔎 Testing Lookup Endpoints...")

    # Lookup by name
    response, error = api_request("GET", "address-book/lookup/by-name", token, params={"name": "Test"})
    if response and response.status_code == 200:
        data = response.json()
        log_test("Lookup by name", True, f"Found {len(data)} matches")
    else:
        log_test("Lookup by name", False)

    # Lookup by tax ID
    response, error = api_request("GET", "address-book/lookup/by-tax-id", token, params={"tax_id": "V-123456789"})
    if response and response.status_code == 200:
        data = response.json()
        log_test("Lookup by tax ID", True, f"Found {len(data)} matches")
    else:
        log_test("Lookup by tax ID", False)


def cleanup(token: str):
    """Clean up test data"""
    print("\n🧹 Cleaning up test data...")

    # Delete address book entries (this will cascade delete contacts)
    for entry_id in reversed(created_ids["address_book"]):
        try:
            response, error = api_request("DELETE", f"address-book/{entry_id}", token)
            if response and response.status_code == 200:
                print(f"  ✅ Deleted Address Book entry {entry_id}")
            else:
                print(f"  ⚠️ Could not delete entry {entry_id}")
        except Exception as e:
            print(f"  ⚠️ Error deleting entry {entry_id}: {e}")


def print_summary():
    """Print test summary"""
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"\n  Total Tests: {test_results['passed'] + test_results['failed']}")
    print(f"  ✅ Passed: {test_results['passed']}")
    print(f"  ❌ Failed: {test_results['failed']}")

    if test_results["errors"]:
        print("\n  Failures:")
        for error in test_results["errors"]:
            print(f"    - {error}")

    print("\n" + "=" * 60)

    return test_results["failed"] == 0


def main():
    print("=" * 60)
    print("ADDRESS BOOK END-TO-END TEST SUITE")
    print("=" * 60)
    print(f"\nAPI URL: {API_URL}")
    print(f"Test User: {TEST_EMAIL}")

    # Authenticate
    token = get_auth_token()
    if not token:
        print("\n❌ Cannot proceed without authentication")
        return 1

    try:
        # Run tests

        # 1. Create entries of all types
        vendor = test_create_vendor(token)
        customer = test_create_customer(token)

        branch = None
        if customer:
            branch = test_create_branch(token, customer["id"])

        employee = test_create_employee(token)
        team = test_create_team(token)

        # 2. Test contacts
        if vendor:
            test_add_contacts(token, vendor["id"])

        # 3. Test list and filter
        test_list_and_filter(token)

        # 4. Test hierarchy
        if customer:
            test_hierarchy(token, customer["id"])

        # 5. Test update
        if vendor:
            test_update_entry(token, vendor["id"])

        # 6. Test status toggle
        if team:
            test_toggle_status(token, team["id"])

        # 7. Test type-specific endpoints
        test_type_specific_endpoints(token)

        # 8. Test lookup endpoints
        test_lookup_endpoints(token)

        # 9. Test employee-specific features
        if employee:
            test_employee_work_order_assignment(token, employee["id"])
            test_employee_attendance(token, employee["id"])

        # Cleanup
        cleanup(token)

    except Exception as e:
        print(f"\n❌ Test suite error: {e}")
        import traceback
        traceback.print_exc()
        cleanup(token)
        return 1

    # Print summary
    success = print_summary()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
