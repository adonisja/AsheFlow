# AsheFlow - Crew Management & Logistics Platform

A comprehensive B2B SaaS solution for delivery crew management, scheduling, logistics coordination, and intelligent dispatching.

## 🚀 Project Overview

AsheFlow is a platform designed to help delivery companies manage their workforce efficiently. The system provides:

- **Crew Management**: Employee profiles, dynamic roles (Driver, Trainer, Walker), team assignments, relationship mapping (favorites/bans).
- **Time Management**: Scheduling, granular Calendar PTO requests, and recurring Day-of-Week Off-Days.
- **Intelligent Dispatching**: Algorithmic generation of daily truck assignments resolving worker preferences, off-days, and role constraints.

## 🏗️ Architecture

### Backend (Python)
- **Framework**: FastAPI
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy 2.0
- **Migrations**: Alembic
- **Authentication**: AWS Cognito (JWT Verification via JWKS)

### Frontend (React)
- **Framework**: React 18 + TypeScript (Vite)
- **State Management**: React Context API
- **UI & Styling**: Tailwind CSS, React-Select
- **API Client**: Axios

### Infrastructure
- **Containerization**: Docker + Docker Compose
- **Provisioning**: Initial seed scripts for rapid populated dev environments (`seed.py`).

## 📁 Project Structure

```text
AsheFlow/
├── backend/                 # Python FastAPI backend
│   ├── alembic/             # Database migrations
│   ├── app/
│   │   ├── api/             # Auth/deps
│   │   ├── models/          # SQLAlchemy Models (Employee, OffDay, Truck, etc.)
│   │   ├── routers/         # API endpoints
│   │   ├── schemas/         # Pydantic schemas
│   │   └── services/        # Business logic (Dispatch Algorithm)
│   ├── seed.py              # Data population script
│   └── requirements.txt
├── frontend/                # React web application
│   ├── src/
│   │   ├── api/             # Axios API bindings
│   │   ├── components/      # Reusable UI (Navbar, Layout, etc.)
│   │   ├── contexts/        # AuthProvider & App State
│   │   ├── pages/           # Pages (Dashboard, Preferences, Schedule)
│   │   └── utils/
│   └── package.json
├── docs/                    # Architecture decisions (ADRs), Diagrams, and Journals
└── docker-compose.yml
```

## 🛠️ Development Setup

### Prerequisites
- Docker & Docker Compose
- AWS Cognito User Pool (Configured with App Client)

### Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/adonisja/AsheFlow.git
   cd AsheFlow
   ```

2. **Environment Variables**
   - Create `backend/.env` based on `backend/.env.example`.
   - Create `frontend/.env` based on `frontend/.env.template`.
   - Ensure AWS Cognito keys (`AWS_COGNITO_USER_POOL_ID` and `AWS_REGION`) are synchronized across both.

3. **Run the Application**
   ```bash
   docker-compose up --build
   ```
   *Alternatively, use the provided `start.sh` script to boot the environment.*

4. **Run Database Migrations & Seed Data**
   Open a new terminal while the containers are running:
   ```bash
   docker exec -it asheflow_backend alembic upgrade head
   docker exec -it asheflow_backend python seed.py
   ```

The application will be available at:
- **Frontend**: http://localhost:3000
- **Backend API Docs**: http://localhost:8000/docs

## 📋 Development Roadmap

- [x] **Phase 1: Data Models & Architecture** - SQL Schema, API bindings, SQLAlchemy setup.
- [x] **Phase 2: Authentication** - AWS Cognito Integration, RBAC setup.
- [x] **Phase 3: Frontend Infrastructure** - Vite + Tailwind layout, base API interceptors.
- [x] **Phase 4: Worker Endpoints** - Preferences tab (Bans/Favs), Scheduling logic (Recurring Off-Days vs Exact Date PTO).
- [ ] **Phase 5: Dispatch Engine UI** - Admin/Management dynamic dashboard for manual and algorithmic truck assignments.

## 📝 Documentations

For deeper technical context, check the `/docs` folder which contains:
- **Journals (`/docs/journals`)**: Chronological daily development logs.
- **Architectural Decision Records (`/docs/decisions`)**: Explanation of system design choices.
- **Learning Guide (`/docs/LEARNING_GUIDE.md`)**: Running list of roadblocks and solutions.
