# MDO Approval System

A FastAPI service for managing MDO (Ministry/Department/Organization) approval requests and workflows. This system allows MDO administrators to review, approve, or reject designation-based approval requests submitted through the iGOT platform.

## Project Overview

This system is part of the iGOT ecosystem and handles the approval workflow for designation requests. MDO administrators can view pending requests, review designation details with competencies and role responsibilities, and take approval actions. The system maintains audit trails and supports bulk operations for efficient processing.

## Project Structure
```
src/
├── main.py                      # FastAPI application entry point
├── api/
│   └── v1/
│       └── mdo_approval.py      # MDO approval endpoints
├── core/
│   ├── configs.py               # Application configuration
│   ├── database.py              # Database connection and session management
│   ├── logger.py                # Logging configuration
│   └── logging.conf             # Logging configuration file
├── crud/
│   └── mdo_approval_request.py  # Database operations for approval requests
├── models/
│   └── mdo_approval.py          # SQLAlchemy models for approval system
├── schemas/
│   ├── comman.py                # Common schemas and enums
│   └── mdo_approval.py          # Pydantic schemas for API requests/responses
├── services/                    # Business logic services (empty)
└── utils/                       # Utility functions (empty)
pyproject.toml                   # Python project configuration
Dockerfile                       # Container configuration
.env                            # Environment variables
```

## Key Features

- **Approval Request Management**: View and manage pending approval requests from various departments
- **Designation Review**: Detailed view of designations with role responsibilities, activities, and competencies
- **Bulk Approval Actions**: Approve or reject multiple designations in a single request
- **Status Tracking**: Automatic status updates (pending → in_review → approved/rejected)
- **Search and Filtering**: Filter requests by status, date range, and search by name
- **Audit Trail**: Complete tracking of approval actions with timestamps and comments
- **Pagination Support**: Efficient handling of large datasets with paginated responses

## Tech Stack

- **Framework**: FastAPI 0.111.0
- **Database**: PostgreSQL with AsyncPG driver
- **ORM**: SQLAlchemy 2.0 (async)
- **Authentication**: JWT with python-jose
- **Validation**: Pydantic v2
- **Package Management**: uv (Python package manager)
- **Containerization**: Docker

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 14+ with pgvector extension
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker (optional, for containerized deployment)

### Installation

```bash
# Clone repository
git clone <repository-url>
cd mdo-approval-system

# Install dependencies using uv
uv sync

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Environment Variables

Create a `.env` file in the project root:

```bash
LOG_LEVEL="INFO"
ENVIRONMENT="local"  # Options: local, staging, production

# Application Settings
APP_NAME="MDO Approval System"
APP_DESC="API for managing MDO approval requests"
APP_VERSION="1.0.0"
APP_ROOT_PATH="/mdo-tpc-ai"

# Database
DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/dbname"

# JWT Authentication
SECRET_KEY="your-secret-key-here"
```

### Run Application

```bash
# Start development server with hot reload
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Access the API at: http://localhost:8000

## Run Using Docker

### Build Docker Image

```bash
docker build -t mdo-approval-system .
```

### Run Container

```bash
docker run -d \
  --name mdo-approval-system \
  -p 8001:8001 \
  --env-file .env \
  mdo-approval-system
```

### Docker Commands

```bash
# View logs
docker logs -f mdo-approval-system

# Stop container
docker stop mdo-approval-system

# Remove container
docker rm mdo-approval-system

# Restart container
docker restart mdo-approval-system
```
## API Documentation

- **Swagger UI**: `http://localhost:8000/docs` (disabled in production)
- **ReDoc**: `http://localhost:8000/redoc` (disabled in production)
- **OpenAPI JSON**: `http://localhost:8000/openapi.json` (disabled in production)

## API Endpoints

All endpoints are under `/api/v1/mdo` and require MDO authentication.

### Approval Request Management

| Method | Endpoint | Description |
|---|---|---|
| GET | `/approval-requests/list` | Get paginated list of approval requests with search and filtering |
| GET | `/approval-requests/{request_id}` | Get detailed view of specific approval request (auto-updates to IN_REVIEW) |
| POST | `/approval-requests/approve` | Approve all designations in a request |
| POST | `/approval-requests/reject` | Reject all designations in a request |
| POST | `/approval-requests/items/reject` | Reject specific designation with comments |

### Query Parameters

**List Endpoint:**
- `mdo_id` (required): MDO ID of the logged-in admin
- `page`: Page number (default: 1)
- `page_size`: Items per page (default: 10, max: 100)
- `search`: Search by request name or state/center name
- `status_filter`: Filter by status (pending, IN_REVIEW, approved, rejected)
- `from_date`: Filter from date (YYYY-MM-DD)
- `to_date`: Filter to date (YYYY-MM-DD)

### Request Bodies

**Approve Request:**
```json
{
  "request_id": "uuid",
  "plan_name": "Training Plan Name",
  "due_date": "2024-12-31T23:59:59Z"
}
```

**Reject Request:**
```json
{
  "request_id": "uuid",
  "rejection_comment": "Reason for rejection"
}
```

**Reject Item:**
```json
{
  "request_id": "uuid",
  "item_id": "uuid",
  "rejection_comment": "Specific reason for rejecting this designation"
}
```

## Database Schema

The system uses three main tables:

### approval_requests
Stores approval request metadata with organization context and status tracking.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| request_name | String(100) | Name of the approval request |
| user_id | UUID | User who submitted the request |
| org_type | String(20) | Organization type (state/center/department) |
| state_center_id | String(255) | State or center identifier |
| department_id | String(255) | Department identifier (optional) |
| mdo_id | String(255) | MDO responsible for approval |
| designation_count | Integer | Number of designations in request |
| status | String(20) | Request status (pending/IN_REVIEW/approved/rejected) |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

### approval_request_items
Stores individual designation details within each approval request.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| approval_request_id | UUID | Foreign key to approval_requests |
| designation_name | String(255) | Name of the designation |
| role_responsibilities | JSONB | Role responsibilities data |
| activities | JSONB | Activities data |
| competencies | JSONB | Competencies data |
| status | String(20) | Item status (pending/approved/rejected) |

### mdo_approval
Tracks MDO approval actions for audit purposes.

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| approval_request_id | UUID | Foreign key to approval_requests |
| approval_request_item_id | UUID | Foreign key to approval_request_items |
| mdo_id | String(255) | MDO who took action |
| designation_name | String(255) | Denormalized designation name |
| plan_name | String(200) | Associated training plan name |
| due_date | DateTime | Plan due date |
| user_id | UUID | Original request submitter |

## Response Examples

### Paginated List Response
```json
{
  "items": [
    {
      "id": "uuid",
      "request_name": "Q1 2024 Designations",
      "state_center_name": "Karnataka",
      "designation_count": 15,
      "status": "pending",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "pagination": {
    "current_page": 1,
    "page_size": 10,
    "total_items": 50,
    "total_pages": 5,
    "has_next": true,
    "has_prev": false
  },
  "filters": {
    "search": null,
    "status_filter": "pending",
    "from_date": null,
    "to_date": null
  }
}
```

### Approval Action Response
```json
{
  "message": "Successfully approved 15 designation(s)",
  "request_status": "approved",
  "items_processed": 15,
  "item_ids": ["uuid1", "uuid2", ...]
}
```

## Troubleshooting

### Database Connection Issues
Ensure PostgreSQL is running and the `DATABASE_URL` is correctly formatted:
```
postgresql+asyncpg://user:password@host:port/dbname
```

### Port Already in Use
If port 8000 or 8001 is already in use, specify a different port:
```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080
```

### JWT Token Issues
Ensure the `SECRET_KEY` matches the one used for token generation. Tokens signed with a different key will be rejected.

### Docker Build Failures
If the Docker build fails on Playwright installation, ensure you have the required system dependencies:
```bash
docker build --build-arg PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0 .
```

## License

This project is part of the iGOT (Integrated Government Online Training) platform.

