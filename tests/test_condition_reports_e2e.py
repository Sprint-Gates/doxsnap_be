#!/usr/bin/env python3
"""
End-to-End Test Suite for Condition Reports API

Tests all Condition Reports functionality including:
- Create condition report
- List condition reports with filtering
- Get single condition report
- Update condition report
- Update status workflow
- Image upload/download/delete
- Stats summary
- Delete condition report

Run from doxsnap_be directory:
    source venv/bin/activate
    python tests/test_condition_reports_e2e.py

Author: Claude Code
Date: 2025-01-08
"""

import os
import sys
import requests
import json
import io
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
    "condition_reports": [],
    "images": [],
    "clients": []
}

# Test results
test_results = {
    "passed": 0,
    "failed": 0,
    "errors": []
}

# Globals for test data
auth_token = None
test_client_id = None
test_site_id = None


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


def api_upload_file(endpoint: str, token: str, file_content: bytes, filename: str,
                    content_type: str = "image/jpeg", form_data: dict = None):
    """Upload file via API"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_URL}/{endpoint}"

    try:
        files = {"file": (filename, io.BytesIO(file_content), content_type)}
        data = form_data or {}

        response = requests.post(url, headers=headers, files=files, data=data)
        return response, None
    except Exception as e:
        return None, str(e)


# ============ Setup Functions ============

def setup_test_client(token: str) -> int:
    """Get or create a test client (using legacy Client table - Condition Reports still uses this)"""
    print("\n🏢 Setting up test client...")

    # Note: Condition Reports API still uses the legacy Client model
    # First try to get existing clients from the clients endpoint
    response, error = api_request("GET", "clients/", token)

    if response and response.status_code == 200:
        clients = response.json()
        if clients and len(clients) > 0:
            client_id = clients[0]["id"]
            print(f"  ✅ Using existing client ID: {client_id}")
            return client_id

    # If clients endpoint doesn't exist or returns empty, try to create via legacy endpoint
    client_data = {
        "name": "Test Client for Condition Reports",
        "email": "test@testclient.com",
        "phone": "+1-555-0200",
        "address": "456 Test Ave",
        "city": "Los Angeles",
        "country": "USA",
        "is_active": True
    }

    response, error = api_request("POST", "clients/", token, client_data)

    if response and response.status_code in [200, 201]:
        client = response.json()
        created_ids["clients"].append(client["id"])
        print(f"  ✅ Created test client ID: {client['id']}")
        return client["id"]

    # Fallback: If we can't access clients API, check if we have a hardcoded known client
    # This is company 1's client from the legacy data
    print(f"  ⚠️ Could not access clients API, using fallback client ID: 22")
    return 22  # Known legacy client ID for company 1


def setup_test_site(token: str, client_id: int) -> int:
    """Get or create a test site"""
    print("\n📍 Setting up test site...")

    # First try to get existing sites
    response, error = api_request("GET", "sites/", token)

    if response and response.status_code == 200:
        sites = response.json()
        if sites and len(sites) > 0:
            site_id = sites[0]["id"]
            print(f"  ✅ Using existing site ID: {site_id}")
            return site_id

    # Create a new site if none exist
    site_data = {
        "address_book_id": client_id,
        "name": "Test Site for Condition Reports",
        "code": "TST-CR-001",
        "address": "789 Test Blvd",
        "city": "San Francisco",
        "country": "USA",
        "is_active": True
    }

    response, error = api_request("POST", "sites/", token, site_data)

    if response and response.status_code in [200, 201]:
        site = response.json()
        print(f"  ✅ Created test site ID: {site['id']}")
        return site["id"]

    print(f"  ⚠️ Could not set up test site: {response.text if response else error}")
    return None


# ============ Test Functions ============

def test_create_condition_report(token: str, client_id: int, site_id: int = None) -> dict:
    """Test creating a condition report"""
    print("\n📝 Testing Create Condition Report...")

    report_data = {
        "client_id": client_id,
        "title": "Water Leak in Main Building",
        "description": "There is a significant water leak detected on the 3rd floor near the elevator shaft. The ceiling tiles are showing water damage and there's a visible drip.",
        "issue_class": "civil",
        "estimated_cost": 5000.00,
        "currency": "USD",
        "location_notes": "3rd Floor, near elevator shaft, Room 301",
        "priority": "high"
    }

    if site_id:
        report_data["site_id"] = site_id

    response, error = api_request("POST", "condition-reports/", token, report_data)

    if error:
        log_test("Create Condition Report", False, f"Request error: {error}")
        return None

    if response.status_code in [200, 201]:
        report = response.json()
        created_ids["condition_reports"].append(report["id"])

        # Validate response structure
        required_fields = ["id", "report_number", "title", "description", "issue_class",
                         "status", "priority", "client_id"]
        missing = [f for f in required_fields if f not in report]

        if missing:
            log_test("Create Condition Report", False, f"Missing fields: {missing}")
            return report

        # Validate initial status is 'submitted'
        if report["status"] != "submitted":
            log_test("Create Condition Report", False, f"Expected status 'submitted', got '{report['status']}'")
            return report

        # Validate report number format (CR-YYYYMMDD-XXX)
        if not report["report_number"].startswith("CR-"):
            log_test("Create Condition Report", False, f"Invalid report number format: {report['report_number']}")
            return report

        log_test("Create Condition Report", True, f"Created report: {report['report_number']}")
        return report
    else:
        log_test("Create Condition Report", False, f"Status {response.status_code}: {response.text}")
        return None


def test_create_condition_report_all_issue_classes(token: str, client_id: int) -> list:
    """Test creating condition reports with all issue classes"""
    print("\n🔧 Testing All Issue Classes...")

    issue_classes = ["civil", "mechanical", "electrical", "others"]
    created_reports = []

    for issue_class in issue_classes:
        report_data = {
            "client_id": client_id,
            "title": f"Test {issue_class.capitalize()} Issue",
            "description": f"Testing {issue_class} issue class creation",
            "issue_class": issue_class,
            "priority": "medium"
        }

        response, error = api_request("POST", "condition-reports/", token, report_data)

        if response and response.status_code in [200, 201]:
            report = response.json()
            created_ids["condition_reports"].append(report["id"])
            created_reports.append(report)
            log_test(f"Create {issue_class.capitalize()} Report", True, f"ID: {report['id']}")
        else:
            log_test(f"Create {issue_class.capitalize()} Report", False,
                    f"{response.text if response else error}")

    return created_reports


def test_create_condition_report_all_priorities(token: str, client_id: int) -> list:
    """Test creating condition reports with all priorities"""
    print("\n⚡ Testing All Priorities...")

    priorities = ["low", "medium", "high", "critical"]
    created_reports = []

    for priority in priorities:
        report_data = {
            "client_id": client_id,
            "title": f"Test {priority.capitalize()} Priority Issue",
            "description": f"Testing {priority} priority creation",
            "issue_class": "civil",
            "priority": priority
        }

        response, error = api_request("POST", "condition-reports/", token, report_data)

        if response and response.status_code in [200, 201]:
            report = response.json()
            created_ids["condition_reports"].append(report["id"])
            created_reports.append(report)
            log_test(f"Create {priority.capitalize()} Priority", True, f"ID: {report['id']}")
        else:
            log_test(f"Create {priority.capitalize()} Priority", False,
                    f"{response.text if response else error}")

    return created_reports


def test_get_condition_reports(token: str) -> list:
    """Test listing condition reports"""
    print("\n📋 Testing List Condition Reports...")

    response, error = api_request("GET", "condition-reports/", token)

    if error:
        log_test("List Condition Reports", False, f"Request error: {error}")
        return []

    if response.status_code == 200:
        reports = response.json()
        log_test("List Condition Reports", True, f"Retrieved {len(reports)} reports")
        return reports
    else:
        log_test("List Condition Reports", False, f"Status {response.status_code}: {response.text}")
        return []


def test_get_condition_reports_with_filters(token: str, client_id: int) -> None:
    """Test listing condition reports with various filters"""
    print("\n🔍 Testing Filtered List...")

    # Test filter by client_id
    response, error = api_request("GET", "condition-reports/", token,
                                  params={"client_id": client_id})
    if response and response.status_code == 200:
        reports = response.json()
        all_match = all(r["client_id"] == client_id for r in reports)
        log_test("Filter by client_id", all_match, f"Found {len(reports)} reports")
    else:
        log_test("Filter by client_id", False, f"{response.text if response else error}")

    # Test filter by issue_class
    response, error = api_request("GET", "condition-reports/", token,
                                  params={"issue_class": "civil"})
    if response and response.status_code == 200:
        reports = response.json()
        all_match = all(r["issue_class"] == "civil" for r in reports)
        log_test("Filter by issue_class", all_match, f"Found {len(reports)} civil reports")
    else:
        log_test("Filter by issue_class", False, f"{response.text if response else error}")

    # Test filter by status
    response, error = api_request("GET", "condition-reports/", token,
                                  params={"status": "submitted"})
    if response and response.status_code == 200:
        reports = response.json()
        all_match = all(r["status"] == "submitted" for r in reports)
        log_test("Filter by status", all_match, f"Found {len(reports)} submitted reports")
    else:
        log_test("Filter by status", False, f"{response.text if response else error}")

    # Test filter by priority
    response, error = api_request("GET", "condition-reports/", token,
                                  params={"priority": "high"})
    if response and response.status_code == 200:
        reports = response.json()
        all_match = all(r["priority"] == "high" for r in reports)
        log_test("Filter by priority", all_match, f"Found {len(reports)} high priority reports")
    else:
        log_test("Filter by priority", False, f"{response.text if response else error}")

    # Test search
    response, error = api_request("GET", "condition-reports/", token,
                                  params={"search": "Water"})
    if response and response.status_code == 200:
        reports = response.json()
        log_test("Search by keyword", True, f"Found {len(reports)} matching reports")
    else:
        log_test("Search by keyword", False, f"{response.text if response else error}")


def test_get_single_condition_report(token: str, report_id: int) -> dict:
    """Test getting a single condition report"""
    print("\n📄 Testing Get Single Report...")

    response, error = api_request("GET", f"condition-reports/{report_id}", token)

    if error:
        log_test("Get Single Report", False, f"Request error: {error}")
        return None

    if response.status_code == 200:
        report = response.json()
        if report["id"] == report_id:
            log_test("Get Single Report", True, f"Report: {report['report_number']}")
            return report
        else:
            log_test("Get Single Report", False, f"ID mismatch: expected {report_id}, got {report['id']}")
            return report
    else:
        log_test("Get Single Report", False, f"Status {response.status_code}: {response.text}")
        return None


def test_update_condition_report(token: str, report_id: int) -> dict:
    """Test updating a condition report"""
    print("\n✏️ Testing Update Condition Report...")

    update_data = {
        "title": "Updated: Water Leak in Main Building - URGENT",
        "description": "UPDATED: The water leak has worsened. Immediate attention required.",
        "estimated_cost": 7500.00,
        "priority": "critical"
    }

    response, error = api_request("PUT", f"condition-reports/{report_id}", token, update_data)

    if error:
        log_test("Update Report", False, f"Request error: {error}")
        return None

    if response.status_code == 200:
        report = response.json()

        # Validate updates
        title_updated = "Updated:" in report["title"]
        cost_updated = report["estimated_cost"] == 7500.00
        priority_updated = report["priority"] == "critical"

        if title_updated and cost_updated and priority_updated:
            log_test("Update Report", True, "All fields updated correctly")
            return report
        else:
            log_test("Update Report", False,
                    f"Some updates failed - title: {title_updated}, cost: {cost_updated}, priority: {priority_updated}")
            return report
    else:
        log_test("Update Report", False, f"Status {response.status_code}: {response.text}")
        return None


def test_update_status_workflow(token: str, report_id: int) -> None:
    """Test status update workflow"""
    print("\n🔄 Testing Status Workflow...")

    # Status transitions: submitted -> under_review -> approved
    statuses = [
        ("under_review", "Reviewing the condition report"),
        ("approved", "Approved for repair work")
    ]

    for new_status, review_notes in statuses:
        update_data = {
            "status": new_status,
            "review_notes": review_notes
        }

        response, error = api_request("PUT", f"condition-reports/{report_id}", token, update_data)

        if response and response.status_code == 200:
            report = response.json()
            if report["status"] == new_status:
                log_test(f"Status -> {new_status}", True)
            else:
                log_test(f"Status -> {new_status}", False,
                        f"Expected '{new_status}', got '{report['status']}'")
        else:
            log_test(f"Status -> {new_status}", False,
                    f"{response.text if response else error}")


def test_get_stats_summary(token: str, client_id: int = None) -> dict:
    """Test getting stats summary"""
    print("\n📊 Testing Stats Summary...")

    params = {}
    if client_id:
        params["client_id"] = client_id

    response, error = api_request("GET", "condition-reports/stats/summary", token, params=params)

    if error:
        log_test("Get Stats Summary", False, f"Request error: {error}")
        return None

    if response.status_code == 200:
        stats = response.json()

        # Validate structure
        required_fields = ["total", "by_status", "by_class", "by_priority", "total_estimated_cost"]
        missing = [f for f in required_fields if f not in stats]

        if missing:
            log_test("Get Stats Summary", False, f"Missing fields: {missing}")
            return stats

        log_test("Get Stats Summary", True,
                f"Total: {stats['total']}, Estimated Cost: ${stats['total_estimated_cost']:.2f}")

        # Print breakdown
        print(f"         By Status: {stats['by_status']}")
        print(f"         By Class: {stats['by_class']}")
        print(f"         By Priority: {stats['by_priority']}")

        return stats
    else:
        log_test("Get Stats Summary", False, f"Status {response.status_code}: {response.text}")
        return None


def test_upload_image(token: str, report_id: int) -> dict:
    """Test uploading an image to a condition report"""
    print("\n📷 Testing Image Upload...")

    # Create a simple test image (1x1 pixel JPEG)
    # This is a minimal valid JPEG file
    test_image_bytes = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
        0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
        0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
        0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
        0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
        0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
        0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
        0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
        0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
        0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
        0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD5, 0xDB, 0x20, 0xB8, 0xF3, 0xFF, 0xD9
    ])

    response, error = api_upload_file(
        f"condition-reports/{report_id}/images",
        token,
        test_image_bytes,
        "test_water_leak.jpg",
        "image/jpeg",
        {"caption": "Photo of water damage on ceiling"}
    )

    if error:
        log_test("Upload Image", False, f"Request error: {error}")
        return None

    if response.status_code in [200, 201]:
        image = response.json()
        created_ids["images"].append({"report_id": report_id, "image_id": image["id"]})

        # Validate response
        if "id" in image and "filename" in image:
            log_test("Upload Image", True, f"Image ID: {image['id']}, File: {image['filename']}")
            return image
        else:
            log_test("Upload Image", False, "Response missing required fields")
            return image
    else:
        log_test("Upload Image", False, f"Status {response.status_code}: {response.text}")
        return None


def test_get_images(token: str, report_id: int) -> list:
    """Test getting images for a condition report"""
    print("\n🖼️ Testing Get Images...")

    response, error = api_request("GET", f"condition-reports/{report_id}/images", token)

    if error:
        log_test("Get Images", False, f"Request error: {error}")
        return []

    if response.status_code == 200:
        images = response.json()
        log_test("Get Images", True, f"Retrieved {len(images)} images")
        return images
    else:
        log_test("Get Images", False, f"Status {response.status_code}: {response.text}")
        return []


def test_update_image(token: str, report_id: int, image_id: int) -> dict:
    """Test updating image caption"""
    print("\n✏️ Testing Update Image...")

    response, error = api_request(
        "PATCH",
        f"condition-reports/{report_id}/images/{image_id}",
        token,
        params={"caption": "Updated caption: Close-up of water damage", "sort_order": 1}
    )

    if error:
        log_test("Update Image", False, f"Request error: {error}")
        return None

    if response.status_code == 200:
        image = response.json()
        if image.get("caption") and "Updated" in image["caption"]:
            log_test("Update Image", True, f"Caption updated")
            return image
        else:
            log_test("Update Image", False, "Caption not updated correctly")
            return image
    else:
        log_test("Update Image", False, f"Status {response.status_code}: {response.text}")
        return None


def test_delete_image(token: str, report_id: int, image_id: int) -> bool:
    """Test deleting an image"""
    print("\n🗑️ Testing Delete Image...")

    response, error = api_request("DELETE", f"condition-reports/{report_id}/images/{image_id}", token)

    if error:
        log_test("Delete Image", False, f"Request error: {error}")
        return False

    if response.status_code == 200:
        result = response.json()
        if result.get("success"):
            log_test("Delete Image", True)
            return True
        else:
            log_test("Delete Image", False, "Response indicates failure")
            return False
    else:
        log_test("Delete Image", False, f"Status {response.status_code}: {response.text}")
        return False


def test_invalid_issue_class(token: str, client_id: int) -> None:
    """Test creating report with invalid issue class"""
    print("\n❌ Testing Invalid Issue Class...")

    report_data = {
        "client_id": client_id,
        "title": "Invalid Test",
        "description": "Testing invalid issue class",
        "issue_class": "invalid_class",
        "priority": "medium"
    }

    response, error = api_request("POST", "condition-reports/", token, report_data)

    if response is not None and response.status_code == 400:
        log_test("Reject Invalid Issue Class", True, "Correctly rejected with 400")
    elif response is not None:
        log_test("Reject Invalid Issue Class", False, f"Expected 400, got {response.status_code}")
    else:
        log_test("Reject Invalid Issue Class", False, f"Request error: {error}")


def test_invalid_priority(token: str, client_id: int) -> None:
    """Test creating report with invalid priority"""
    print("\n❌ Testing Invalid Priority...")

    report_data = {
        "client_id": client_id,
        "title": "Invalid Test",
        "description": "Testing invalid priority",
        "issue_class": "civil",
        "priority": "invalid_priority"
    }

    response, error = api_request("POST", "condition-reports/", token, report_data)

    if response is not None and response.status_code == 400:
        log_test("Reject Invalid Priority", True, "Correctly rejected with 400")
    elif response is not None:
        log_test("Reject Invalid Priority", False, f"Expected 400, got {response.status_code}")
    else:
        log_test("Reject Invalid Priority", False, f"Request error: {error}")


def test_nonexistent_report(token: str) -> None:
    """Test getting a non-existent report"""
    print("\n❌ Testing Non-existent Report...")

    response, error = api_request("GET", "condition-reports/999999", token)

    if response is not None and response.status_code == 404:
        log_test("Non-existent Report Returns 404", True)
    elif response is not None:
        log_test("Non-existent Report Returns 404", False, f"Expected 404, got {response.status_code}")
    else:
        log_test("Non-existent Report Returns 404", False, f"Request error: {error}")


def test_delete_condition_report(token: str, report_id: int) -> bool:
    """Test deleting a condition report"""
    print("\n🗑️ Testing Delete Condition Report...")

    response, error = api_request("DELETE", f"condition-reports/{report_id}", token)

    if error:
        log_test("Delete Report", False, f"Request error: {error}")
        return False

    if response.status_code == 200:
        result = response.json()
        if result.get("success"):
            log_test("Delete Report", True, f"Deleted report ID: {report_id}")
            # Remove from created_ids since it's deleted
            if report_id in created_ids["condition_reports"]:
                created_ids["condition_reports"].remove(report_id)
            return True
        else:
            log_test("Delete Report", False, "Response indicates failure")
            return False
    else:
        log_test("Delete Report", False, f"Status {response.status_code}: {response.text}")
        return False


# ============ Cleanup ============

def cleanup(token: str):
    """Clean up test data"""
    print("\n🧹 Cleaning up test data...")

    # Delete condition reports (this also deletes images via cascade)
    for report_id in created_ids["condition_reports"][:]:
        response, _ = api_request("DELETE", f"condition-reports/{report_id}", token)
        if response and response.status_code == 200:
            print(f"  ✅ Deleted condition report {report_id}")
            created_ids["condition_reports"].remove(report_id)
        else:
            print(f"  ⚠️ Failed to delete condition report {report_id}")

    # Note: We don't delete clients as they may be used by other tests

    print("  ✅ Cleanup complete")


# ============ Main Test Runner ============

def main():
    """Run all tests"""
    global auth_token, test_client_id, test_site_id

    print("=" * 60)
    print("🧪 CONDITION REPORTS END-TO-END TEST SUITE")
    print("=" * 60)
    print(f"API URL: {API_URL}")
    print(f"Test User: {TEST_EMAIL}")

    # Authenticate
    auth_token = get_auth_token()
    if not auth_token:
        print("\n❌ Cannot proceed without authentication")
        return

    # Setup test data
    test_client_id = setup_test_client(auth_token)
    if not test_client_id:
        print("\n❌ Cannot proceed without test client")
        return

    test_site_id = setup_test_site(auth_token, test_client_id)

    try:
        # ========== CREATE TESTS ==========
        report = test_create_condition_report(auth_token, test_client_id, test_site_id)
        report_id = report["id"] if report else None

        if report_id:
            # Additional create tests
            test_create_condition_report_all_issue_classes(auth_token, test_client_id)
            test_create_condition_report_all_priorities(auth_token, test_client_id)

            # ========== READ TESTS ==========
            test_get_condition_reports(auth_token)
            test_get_condition_reports_with_filters(auth_token, test_client_id)
            test_get_single_condition_report(auth_token, report_id)

            # ========== UPDATE TESTS ==========
            test_update_condition_report(auth_token, report_id)
            test_update_status_workflow(auth_token, report_id)

            # ========== STATS TESTS ==========
            test_get_stats_summary(auth_token)
            test_get_stats_summary(auth_token, test_client_id)

            # ========== IMAGE TESTS ==========
            image = test_upload_image(auth_token, report_id)
            if image:
                image_id = image["id"]
                test_get_images(auth_token, report_id)
                test_update_image(auth_token, report_id, image_id)

                # Upload another image for delete test
                image2 = test_upload_image(auth_token, report_id)
                if image2:
                    test_delete_image(auth_token, report_id, image2["id"])

            # ========== VALIDATION TESTS ==========
            test_invalid_issue_class(auth_token, test_client_id)
            test_invalid_priority(auth_token, test_client_id)
            test_nonexistent_report(auth_token)

            # ========== DELETE TESTS ==========
            # Create a report specifically for delete test
            delete_test_report = test_create_condition_report(auth_token, test_client_id)
            if delete_test_report:
                test_delete_condition_report(auth_token, delete_test_report["id"])

    finally:
        # Cleanup
        cleanup(auth_token)

    # Print summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    print(f"  ✅ Passed: {test_results['passed']}")
    print(f"  ❌ Failed: {test_results['failed']}")
    print(f"  📈 Total:  {test_results['passed'] + test_results['failed']}")

    if test_results["errors"]:
        print("\n⚠️ Failed Tests:")
        for error in test_results["errors"]:
            print(f"  - {error}")

    # Exit with appropriate code
    if test_results["failed"] > 0:
        print("\n❌ Some tests failed!")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
