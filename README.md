# MDO Approval System

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0_async-red.svg)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14+-336791.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg)](https://www.docker.com/)
[![iGOT](https://img.shields.io/badge/platform-iGOT-orange.svg)](https://igotkarmayogi.gov.in/)

A FastAPI microservice that powers the **MDO-side approval workflow** for CBP (Competency-Based Plan) requests originating from the CBP portal.

---

## Table of Contents

- [MDO Approval System](#mdo-approval-system)
  - [Table of Contents](#table-of-contents)
  - [Project Overview](#project-overview)
  - [Project Structure](#project-structure)
  - [Key Features](#key-features)
  - [Tech Stack](#tech-stack)
  - [Quick Start](#quick-start)
    - [Prerequisites](#prerequisites)
    - [Installation](#installation)
    - [Environment Variables](#environment-variables)
    - [Run Application](#run-application)
  - [Run Using Docker](#run-using-docker)
    - [Build \& Run](#build--run)
    - [Common Docker Commands](#common-docker-commands)

---

## Project Overview

This service is the MDO-side approval layer of the iGOT ecosystem. The workflow begins on the CBP portal, where users create CBP plans linked to designations (with role responsibilities, activities, and competencies). These plans are submitted as approval requests and arrive in this service with a `PENDING` status, awaiting review by the responsible MDO administrator.

**End-to-end flow:**

```
CBP Portal
  └─ User creates CBP plan (designations + courses/competencies)
       └─ Submits for approval → approval_request (PENDING) stored in DB
            └─ MDO Admin reviews via this service
                 ├─ APPROVE → calls iGOT CBP Create API + Publish API → status = APPROVED
                 └─ REJECT  → stores rejection comments               → status = REJECTED
```

MDO administrators can view pending requests, drill into designation details, and take approval actions individually or in bulk. The system maintains a full audit trail of every action.

---

## Project Structure

```
src/
├── main.py                       # FastAPI application entry point
├── api/
│   └── v1/
│       └── mdo_approval.py       # MDO approval endpoints
├── controller/
│   └── mdo_approval.py           # Business logic / orchestration layer
├── core/
│   ├── configs.py                # Application configuration
│   ├── database.py               # Database connection and session management
│   ├── logger.py                 # Logging configuration
│   └── logging.conf              # Logging configuration file
├── crud/
│   └── mdo_approval_request.py   # Database operations for approval requests
├── models/
│   └── mdo_approval.py           # SQLAlchemy models for approval system
├── schemas/
│   ├── comman.py                 # Common schemas and enums
│   └── mdo_approval.py           # Pydantic schemas for API requests/responses
└── services/
    └── igot_service.py           # iGOT CBP plan create & publish API integration
pyproject.toml                    # Python project configuration
Dockerfile                        # Container configuration
.env                              # Environment variables
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| **CBP → MDO Flow** | CBP plans from the CBP portal arrive as `PENDING` requests for MDO review |
| **Designation Review** | Detailed view of designations with role responsibilities, activities, and competencies |
| **Two-Step iGOT Integration** | On approval, calls the iGOT CBP **Create** API then the **Publish** API; stores the returned `publish_id` |
| **Bulk Approval / Rejection** | Approve or reject all designations in a request in a single call |
| **Item-Level Rejection** | Reject individual designations with specific reviewer comments |
| **Status Tracking** | `PENDING` → `APPROVED` / `REJECTED` with automatic transitions |
| **Search & Filtering** | Filter by status, date range, or search by request / org name |
| **Audit Trail** | Full history of MDO actions with timestamps and comments |
| **Pagination** | Efficient pagination for large datasets |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI 0.111.0 |
| Database | PostgreSQL 14+ with AsyncPG driver |
| ORM | SQLAlchemy 2.0 (async) |
| Auth | JWT via python-jose |
| Validation | Pydantic v2 |
| Package Manager | [uv](https://docs.astral.sh/uv/) |
| Containerisation | Docker |

---

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 14+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker *(optional, for containerised deployment)*

### Installation

```bash
# Clone repository
git clone <repository-url>
cd cbp-ai-mdo-service

# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

### Environment Variables

Create a `.env` file in the project root:

```bash
LOG_LEVEL="INFO"
ENVIRONMENT="local"              # local | staging | production

# Application
APP_NAME="MDO Approval System"
APP_DESC="API for managing MDO approval requests"
APP_VERSION="1.0.0"
APP_ROOT_PATH="/mdo-tpc-ai"

# Database
DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/dbname"

# JWT Authentication
SECRET_KEY="your-secret-key-here"

# Role required to access MDO endpoints
# Default: PUBLIC — set to cbp_creator in staging/production
REQUIRED_ROLE="cbp_creator"

# iGOT / Karmayogi Bharat portal
KB_BASE_URL="https://portal.dev.karmayogibharat.net"
KB_AUTH_TOKEN="your-kb-auth-token-here"
```

> **Note**: `KB_BASE_URL` and `KB_AUTH_TOKEN` are required for the approval (publish) flow. Without them, the iGOT Create and Publish API calls will fail.

### Run Application

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

API available at: `http://localhost:8000`

---

## Run Using Docker

### Build & Run

```bash
# Build image
docker build -t mdo-approval-system .

# Run container
docker run -d \
  --name mdo-approval-system \
  -p 8001:8001 \
  --env-file .env \
  mdo-approval-system
```

### Common Docker Commands

```bash
docker logs -f mdo-approval-system    # Stream logs
docker stop mdo-approval-system       # Stop container
docker rm mdo-approval-system         # Remove container
docker restart mdo-approval-system    # Restart container
```
