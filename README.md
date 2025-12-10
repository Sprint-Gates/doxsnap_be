# DoxSnap Backend

A comprehensive multi-tenant backend API for document processing, field service management, and maintenance operations built with FastAPI and Python.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [API Documentation](#api-documentation)
- [Database Schema](#database-schema)
- [Business Logic](#business-logic)
- [Deployment](#deployment)

---

## Overview

DoxSnap Backend is an enterprise-grade API that powers a complete field service and maintenance management platform. It combines AI-powered document processing with comprehensive asset management, work order tracking, and inventory control.

### Core Capabilities

1. **Document Intelligence** - Upload invoices/documents and automatically extract structured data using OCR and Google Gemini AI
2. **Multi-Tenant Architecture** - Support multiple companies with complete data isolation
3. **Asset Management** - Hierarchical tracking of facilities, equipment, and components
4. **Work Order System** - Full lifecycle management of maintenance tasks
5. **Preventive Maintenance** - Schedule-based PM with checklists and activities
6. **Inventory Management** - Warehouses, stock levels, transfers, and item ledger
7. **Field Service** - Technician management, handheld devices, and attendance tracking

---

## Features

### Document Processing
- Upload images and PDFs for automatic processing
- OCR text extraction using Tesseract
- AI-powered structured data extraction (invoice number, date, line items, totals)
- Vendor auto-matching and suggestions
- Confidence scoring for extracted fields
- Reprocessing capability for improved results

### Organization Management
- **Companies** - Multi-tenant organization support with subscription plans
- **Clients** - Customer management per company
- **Branches** - Physical locations with floor/room hierarchy
- **Projects** - Project tracking with cost centers and markup configuration

### Personnel Management
- **Operators** - Field operators with branch assignments
- **Technicians** - Service technicians with specializations, hourly rates, and salary tracking
- **Attendance** - Check-in/check-out with GPS, leave management, overtime tracking

### Asset & Equipment
- **Equipment** - Asset registry with serial numbers, warranty, condition tracking
- **Sub-Equipment** - Component/part management
- **Location Hierarchy** - Branch → Floor → Room → Equipment structure
- **QR Codes** - Equipment identification support

### Work Orders
- **Types** - Corrective, preventive, and operations work orders
- **Assignment** - Multi-technician assignment with hourly rate snapshots
- **Time Tracking** - Per-technician time entries with overtime calculation
- **Parts Tracking** - Issue items from warehouse/HHD stock to work orders
- **Checklists** - PM checklist items with completion tracking
- **Costing** - Labor cost, parts cost, markup, and billable amount calculation
- **Approval Workflow** - Admin/accounting approval with lock mechanism

### Preventive Maintenance
- **Equipment Classes** - Level 1 categorization (HVAC, Electrical, etc.)
- **System Codes** - Level 2 categorization (Heating, Cooling, etc.)
- **Asset Types** - Level 3 categorization with maintenance checklists
- **Activities** - Detailed maintenance tasks with estimated duration
- **Frequencies** - 1W, 1M, 3M, 6M, 1Y scheduling options
- **PM Schedules** - Track due dates and generate work orders

### Inventory Management
- **Item Master** - Comprehensive product catalog with categories
- **Item Categories** - CV, EL, TL, PL, MC, LGH, SAN, HVC classifications
- **Warehouses** - Multiple warehouse support with main warehouse designation
- **HHD Stock** - Handheld device inventory for field technicians
- **Stock Transfers** - Warehouse-to-warehouse and warehouse-to-HHD transfers
- **Item Ledger** - Complete transaction history with running balances
- **Reservation System** - Hold items for unapproved work orders

### Handheld Devices
- Device inventory and status management
- Technician assignment (single or warehouse-based)
- Stock level tracking per device
- Sync status monitoring

### Authentication & Security
- JWT-based authentication with configurable expiry
- Role-based access control (admin, operator, accounting)
- OTP verification for email and password reset
- Password hashing with bcrypt
- Multi-tenant data isolation

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI 0.115.0 |
| Language | Python 3.11+ |
| ORM | SQLAlchemy 2.0.23 |
| Database | PostgreSQL / SQLite |
| Auth | JWT (python-jose), bcrypt (passlib) |
| File Storage | AWS S3 (boto3) |
| AI/OCR | Google Gemini, Tesseract (pytesseract) |
| Image Processing | Pillow, OpenCV |
| PDF Processing | PyMuPDF, ReportLab |
| Email | SMTP (Office 365) |
| Validation | Pydantic 2.x |
| Excel | openpyxl |

---

## Getting Started

### Prerequisites

- Python 3.11 or higher
- PostgreSQL 12+ (or SQLite for development)
- Tesseract OCR installed on system
- AWS S3 bucket for file storage
- Google API key for Gemini AI
- SMTP credentials for email

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Sprint-Gates/doxsnap_be.git
   cd doxsnap_be
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # macOS/Linux
   # or
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Tesseract OCR**
   ```bash
   # macOS
   brew install tesseract

   # Ubuntu/Debian
   sudo apt-get install tesseract-ocr

   # Windows - Download installer from GitHub
   ```

5. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

6. **Run the server**
   ```bash
   # Development
   python run.py
   # or
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload

   # Production
   uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

7. **Access the API**
   - Base URL: http://localhost:8000
   - Swagger Docs: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

---

## Configuration

### Environment Variables

Create a `.env` file with the following variables:

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/doxsnap_db
# Or for SQLite development:
# DATABASE_URL=sqlite:///./app.db

# Alternative database config (if not using DATABASE_URL)
DB_USERNAME=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=doxsnap_db

# Authentication
SECRET_KEY=your-super-secret-key-minimum-32-characters
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# AWS S3
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_REGION=eu-central-1
S3_BUCKET=doxsnap

# Google AI (Gemini)
GOOGLE_API_KEY=your-google-gemini-api-key

# Email (SMTP)
SMTP_SERVER=smtp.office365.com
SMTP_PORT=587
SMTP_USERNAME=noreply@yourdomain.com
SMTP_PASSWORD=your_app_password
COMPANY_SUPPORT_EMAIL=support@yourdomain.com
```

---

## API Documentation

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/register` | Register new user |
| POST | `/api/login` | User login (returns JWT) |
| GET | `/api/me` | Get current user info |
| PUT | `/api/profile` | Update user profile |
| POST | `/api/reset-password` | Initiate password reset |

### OTP Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/otp/send` | Send OTP to email |
| POST | `/api/otp/verify` | Verify OTP code |
| POST | `/api/otp/resend` | Resend OTP |

### Document Processing

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/images/upload` | Upload and process document |
| GET | `/api/images` | List processed documents |
| GET | `/api/images/{id}` | Get document details |
| DELETE | `/api/images/{id}` | Delete document |
| POST | `/api/admin/images/{id}/reprocess` | Reprocess with AI |

### Organization Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/companies` | Company CRUD |
| GET/POST | `/api/clients` | Client CRUD |
| GET/POST | `/api/branches` | Branch CRUD |
| GET/POST | `/api/projects` | Project CRUD |

### Work Orders

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/work-orders` | List work orders |
| POST | `/api/work-orders` | Create work order |
| GET | `/api/work-orders/{id}` | Get work order details |
| PUT | `/api/work-orders/{id}` | Update work order |
| POST | `/api/work-orders/{id}/approve` | Approve work order |
| POST | `/api/work-orders/{id}/technicians/{tech_id}` | Assign technician |
| POST | `/api/work-orders/{id}/time-entries` | Add time entry |
| POST | `/api/work-orders/{id}/issue-item` | Issue item from stock |
| POST | `/api/work-orders/{id}/return-item` | Return item to stock |
| GET | `/api/work-orders/{id}/costs` | Calculate costs |

### Inventory Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/item-master` | Item catalog CRUD |
| GET/POST | `/api/item-categories` | Categories CRUD |
| GET/POST | `/api/warehouses` | Warehouse CRUD |
| GET | `/api/warehouses/{id}/stock` | Warehouse stock levels |
| POST | `/api/item-transfers` | Create stock transfer |
| GET | `/api/item-ledger` | Transaction history |
| GET | `/api/hhd/{id}/stock` | HHD stock levels |

### Preventive Maintenance

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pm/equipment-classes` | Equipment classes |
| GET | `/api/pm/system-codes` | System codes |
| GET | `/api/pm/asset-types` | Asset types with checklists |
| POST | `/api/pm/generate-work-orders` | Generate PM work orders |

### Personnel

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/technicians` | Technician CRUD |
| GET/POST | `/api/operators` | Operator CRUD |
| GET/POST | `/api/handheld-devices` | HHD CRUD |
| GET/POST | `/api/attendance` | Attendance records |

---

## Database Schema

### Core Entities

```
Company (Multi-tenant root)
├── Users (Authentication & profiles)
├── Clients (Customers)
│   └── Branches (Locations)
│       ├── Projects (Cost centers)
│       └── Floors → Rooms → Equipment → SubEquipment
├── Technicians (Field workers)
│   └── Attendance Records
├── Operators (Equipment operators)
├── Vendors (Suppliers)
├── Warehouses
│   └── Item Stock
├── Handheld Devices
│   └── Item Stock
├── Item Categories
│   └── Item Master
│       └── Item Ledger
└── Work Orders
    ├── Time Entries
    ├── Checklist Items
    └── Issued Items (via Item Ledger)
```

### Key Relationships

- **Multi-tenancy**: All entities scoped to Company
- **Work Orders**: Link to Equipment, Technicians, Project, HHD
- **Inventory**: Stock tracked per Warehouse and HHD location
- **Item Ledger**: Tracks all movements with source references
- **PM System**: Equipment Class → System Code → Asset Type → Checklist → Activities

---

## Business Logic

### Work Order Lifecycle

1. **Draft** - Initial creation, can be edited freely
2. **Open** - Assigned and ready for work
3. **In Progress** - Work started, time entries being logged
4. **Completed** - Work finished, costs calculated
5. **Approved** - Locked by admin/accounting, items permanently deducted

### Item Reservation System

When items are issued to unapproved work orders:
1. Items are **reserved** (quantity_reserved increases)
2. Available stock = quantity_on_hand - quantity_reserved
3. Reserved items cannot be issued elsewhere
4. On work order approval, reserved items are permanently deducted
5. On item return, reservation is released

### Cost Calculation

```
Labor Cost = Σ (hours_worked × hourly_rate) for all time entries
Parts Cost = Σ (quantity × unit_cost) for all issued items
Total Cost = Labor Cost + Parts Cost
Billable Amount = (Labor × (1 + labor_markup%)) + (Parts × (1 + parts_markup%))
```

### PM Schedule Generation

1. System tracks last completed PM date per equipment/checklist
2. Next due date = last_completed + frequency_days
3. Generate PM work orders when due date approaches
4. Activities copied from checklist template to work order

---

## Deployment

### Docker

```dockerfile
# Build
docker build -t doxsnap-backend .

# Run
docker run -p 8000:8000 --env-file .env doxsnap-backend
```

### Docker Compose

```yaml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: doxsnap_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### Production Considerations

- Use PostgreSQL (not SQLite)
- Set strong SECRET_KEY (32+ characters)
- Configure proper CORS origins
- Use HTTPS/TLS termination
- Set appropriate worker count based on CPU cores
- Configure logging and monitoring
- Set up database backups
- Use environment-specific .env files

---

## Project Structure

```
backend/
├── main.py                 # FastAPI app initialization
├── run.py                  # Startup script
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container build
├── .env.example            # Environment template
├── app/
│   ├── config.py           # Settings management
│   ├── database.py         # SQLAlchemy setup
│   ├── models.py           # Database models
│   ├── schemas.py          # Pydantic schemas
│   ├── api/                # Route handlers
│   │   ├── auth.py
│   │   ├── work_orders.py
│   │   ├── item_master.py
│   │   └── ... (20+ modules)
│   ├── services/           # Business logic
│   │   ├── auth.py
│   │   ├── s3.py
│   │   ├── otp.py
│   │   ├── email.py
│   │   └── enhanced_invoice_processing.py
│   └── utils/              # Utilities
│       ├── security.py
│       └── pm_seed.py
├── templates/              # HTML templates
├── uploads/                # Temporary uploads
└── misc/                   # Migrations, scripts, docs
```

---

## License

Proprietary - Sprint Gates

## Support

For issues and questions, contact: support@sprintgates.com
