# AsheFlow MVP Development Plan

## 🎯 MVP Scope Definition

### Core Features (Must Have)
1. ✅ **Time Management**
   - Driver clock in/out with GPS
   - Timesheet generation
   - Hours worked tracking
   
2. ✅ **Route Management**
   - Route assignment to drivers
   - Package list per route
   - Delivery status updates
   
3. ✅ **Approval Workflow**
   - Management timesheet review
   - Approve/reject with notes
   - Status tracking

4. ✅ **Multi-Role Dashboard**
   - Driver: My route, my hours
   - Dispatch: Assign routes, monitor deliveries
   - Management: Approve timesheets, view reports

### User Roles (All in MVP)
- Driver
- Walker (subset of Driver features)
- Dispatch
- Management

### Data Sources (MVP Approach)
- Mock/Sample data for routes and packages
- Real data for time entries and approvals
- Adapter pattern for future ADP/Cortex integration

---

## 🏗️ System Architecture Explained

### **Layer 1: Client Applications**

#### Mobile App (React Native)
**Users**: Driver, Walker
**Key Screens**:
- Login
- Dashboard (today's route, hours worked)
- Clock In/Out
- Route details
- Package list with status updates
- Delivery confirmation (photo, signature)

#### Web App (React)
**Users**: Dispatch, Management
**Key Screens**:
- Login
- Dashboard (role-based)
- Route assignment interface
- Live delivery tracking map
- Timesheet approval interface
- Employee management
- Reports

### **Layer 2: API Gateway**
**Purpose**: Single entry point for all API calls
**Responsibilities**:
- Authentication (JWT validation)
- Request routing to appropriate service
- Rate limiting
- CORS handling
- Request/response logging

**Implementation**: FastAPI middleware

### **Layer 3: Backend Services**

#### 1. Auth Service
```python
Endpoints:
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh-token
POST /api/v1/auth/logout
GET  /api/v1/auth/me

Responsibilities:
- User registration
- Password hashing (bcrypt)
- JWT token generation
- Role-based access control
- Session management
```

#### 2. Employee Service
```python
Endpoints:
GET    /api/v1/employees
POST   /api/v1/employees
GET    /api/v1/employees/{id}
PUT    /api/v1/employees/{id}
DELETE /api/v1/employees/{id}
GET    /api/v1/employees/{id}/profile

Responsibilities:
- Employee CRUD operations
- Profile management
- Role assignment
- Multi-tenant isolation
```

#### 3. Time Management Service
```python
Endpoints:
POST   /api/v1/time/clock-in
POST   /api/v1/time/clock-out
GET    /api/v1/time/entries
GET    /api/v1/time/entries/current
GET    /api/v1/timesheets
GET    /api/v1/timesheets/{id}
PUT    /api/v1/timesheets/{id}

Responsibilities:
- Clock in/out recording
- GPS location validation
- Hours calculation
- Timesheet generation
- Break tracking
```

#### 4. Route Management Service
```python
Endpoints:
GET    /api/v1/routes
POST   /api/v1/routes (for dispatch)
GET    /api/v1/routes/{id}
PUT    /api/v1/routes/{id}/assign
GET    /api/v1/routes/my-route (for drivers)
GET    /api/v1/packages
PUT    /api/v1/packages/{id}/status

Responsibilities:
- Route CRUD
- Driver assignment
- Package management
- Status tracking
- Real-time updates
```

#### 5. Approval Workflow Service
```python
Endpoints:
GET    /api/v1/approvals/timesheets/pending
POST   /api/v1/approvals/timesheets/{id}/approve
POST   /api/v1/approvals/timesheets/{id}/reject
GET    /api/v1/approvals/history

Responsibilities:
- Approval workflow state machine
- Notification triggers
- Audit logging
- Status transitions
```

### **Layer 4: Data Layer**

#### PostgreSQL Database
**Schema Overview**:
```sql
-- Multi-tenancy
companies (tenants)
users
roles
permissions

-- Employee Management
employees
employee_documents
teams

-- Time Management
time_entries
timesheets
timesheet_approvals

-- Route & Logistics
routes
packages
delivery_status_log

-- Audit
audit_logs
```

#### Redis Cache
**Usage**:
- Session storage (JWT tokens)
- Real-time delivery status
- Active route cache
- Rate limiting counters
- Pub/Sub for notifications

### **Layer 5: Background Jobs (Celery)**

**Tasks**:
1. **End-of-day timesheet generation** (scheduled)
2. **Notification delivery** (async)
3. **Report generation** (scheduled)
4. **Data sync with external systems** (future)
5. **GPS data processing**

---

## 📊 Database Schema Design

### Core Tables Structure

```sql
-- Multi-tenancy foundation
CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Users and authentication
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL, -- driver, walker, dispatch, management
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Employee profiles
CREATE TABLE employees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    user_id UUID REFERENCES users(id),
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    employee_number VARCHAR(50),
    hire_date DATE,
    hourly_rate DECIMAL(10,2), -- Visible only to management
    adp_id VARCHAR(100), -- For future ADP sync
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Time tracking
CREATE TABLE time_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    employee_id UUID REFERENCES employees(id),
    clock_in_time TIMESTAMP NOT NULL,
    clock_in_location JSONB, -- {lat, lon, accuracy}
    clock_out_time TIMESTAMP,
    clock_out_location JSONB,
    duration_minutes INTEGER,
    status VARCHAR(50) DEFAULT 'active', -- active, completed
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Timesheet aggregation
CREATE TABLE timesheets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    employee_id UUID REFERENCES employees(id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_hours DECIMAL(10,2),
    total_overtime_hours DECIMAL(10,2),
    status VARCHAR(50) DEFAULT 'pending', -- pending, approved, rejected
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMP,
    rejection_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Routes (from Cortex in future, mock data for MVP)
CREATE TABLE routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    route_number VARCHAR(50) NOT NULL,
    route_date DATE NOT NULL,
    assigned_driver_id UUID REFERENCES employees(id),
    status VARCHAR(50) DEFAULT 'planned', -- planned, in_progress, completed
    total_packages INTEGER,
    completed_packages INTEGER DEFAULT 0,
    cortex_route_id VARCHAR(100), -- For future Cortex sync
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Packages
CREATE TABLE packages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    route_id UUID REFERENCES routes(id),
    tracking_number VARCHAR(100) NOT NULL,
    recipient_name VARCHAR(255),
    delivery_address TEXT,
    status VARCHAR(50) DEFAULT 'pending', -- pending, loaded, in_transit, delivered, exception
    delivered_at TIMESTAMP,
    cortex_package_id VARCHAR(100), -- For future Cortex sync
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Audit logging
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id UUID,
    changes JSONB,
    ip_address VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 🛠️ Technology Stack Breakdown

### Backend
```yaml
Language: Python 3.11+
Framework: FastAPI 0.109+
Database: PostgreSQL 15+
ORM: SQLAlchemy 2.0
Migrations: Alembic
Task Queue: Celery 5+
Message Broker: Redis 7+
Auth: python-jose (JWT), passlib (bcrypt)
Validation: Pydantic v2
Testing: pytest, pytest-asyncio
```

### Frontend
```yaml
Web Framework: React 18+ TypeScript
Mobile Framework: React Native 0.72+
State Management: Redux Toolkit
UI Library: Material-UI (MUI) or Tailwind CSS
API Client: Axios + React Query
Forms: React Hook Form
Charts: Recharts or Chart.js
Maps: Mapbox or Google Maps API
```

### DevOps
```yaml
Containerization: Docker + Docker Compose
CI/CD: GitHub Actions
Monitoring: Prometheus + Grafana (future)
Logging: Python logging + ELK stack (future)
```

---

## 📅 Development Phases

### **Phase 1: Foundation (Weeks 1-2)**

#### Week 1: Backend Setup
**Learning Focus**: FastAPI, Database Design, Authentication

**Tasks**:
1. ✅ Set up FastAPI project structure
2. ✅ Configure PostgreSQL with Docker
3. ✅ Set up SQLAlchemy models
4. ✅ Configure Alembic migrations
5. ✅ Implement authentication (JWT)
6. ✅ Create User and Employee models
7. ✅ Build Auth endpoints (register, login, logout)
8. ✅ Test with Postman/curl

**Deliverable**: Working authentication API

#### Week 2: Core Data Models
**Learning Focus**: Database relationships, Multi-tenancy, RBAC

**Tasks**:
1. ✅ Implement multi-tenant middleware
2. ✅ Create TimeEntry model and endpoints
3. ✅ Create Route and Package models
4. ✅ Build RBAC permission system
5. ✅ Write database seed script with mock data
6. ✅ Test role-based access

**Deliverable**: Complete database schema with test data

---

### **Phase 2: Core Features (Weeks 3-5)**

#### Week 3: Time Management
**Learning Focus**: Business logic, GPS handling, State machines

**Tasks**:
1. ✅ Clock in/out endpoints
2. ✅ GPS location validation
3. ✅ Hours calculation logic
4. ✅ Timesheet generation service
5. ✅ Break tracking
6. ✅ Write unit tests

**Deliverable**: Working time tracking API

#### Week 4: Route Management
**Learning Focus**: CRUD operations, Complex queries, Mock data

**Tasks**:
1. ✅ Route CRUD endpoints
2. ✅ Package assignment logic
3. ✅ Driver assignment service
4. ✅ Status update endpoints
5. ✅ Real-time updates with Redis
6. ✅ Create mock Cortex data generator

**Deliverable**: Route management API with mock data

#### Week 5: Approval Workflow
**Learning Focus**: State machines, Business processes, Notifications

**Tasks**:
1. ✅ Approval workflow state machine
2. ✅ Timesheet approval endpoints
3. ✅ Rejection with notes
4. ✅ Email notification system (Celery)
5. ✅ Audit logging
6. ✅ Permission checks

**Deliverable**: Complete approval workflow

---

### **Phase 3: Frontend Development (Weeks 6-8)**

#### Week 6: Web App Foundation
**Learning Focus**: React, TypeScript, API integration

**Tasks**:
1. ✅ Set up React + TypeScript project
2. ✅ Configure Redux Toolkit
3. ✅ Set up React Query
4. ✅ Build authentication flow
5. ✅ Create layout components
6. ✅ Implement routing

**Deliverable**: Web app shell with login

#### Week 7: Dashboard & Features
**Learning Focus**: Component design, State management, UX

**Tasks**:
1. ✅ Management dashboard
2. ✅ Dispatch route assignment UI
3. ✅ Timesheet approval interface
4. ✅ Employee management screens
5. ✅ Real-time status updates

**Deliverable**: Functional web application

#### Week 8: Mobile App (Driver Interface)
**Learning Focus**: React Native, Mobile UX, GPS

**Tasks**:
1. ✅ Set up React Native project
2. ✅ Build driver login
3. ✅ Clock in/out screens with GPS
4. ✅ Route view
5. ✅ Package list with status updates
6. ✅ Photo capture for delivery proof

**Deliverable**: Driver mobile app MVP

---

### **Phase 4: Integration & Polish (Weeks 9-10)**

#### Week 9: Background Jobs & Testing
**Learning Focus**: Celery, Testing strategies, CI/CD

**Tasks**:
1. ✅ Set up Celery workers
2. ✅ Implement scheduled tasks
3. ✅ Write comprehensive tests
4. ✅ Set up GitHub Actions CI
5. ✅ Performance testing

**Deliverable**: Robust, tested system

#### Week 10: Deployment & Documentation
**Learning Focus**: Docker, Cloud deployment, Documentation

**Tasks**:
1. ✅ Finalize Docker setup
2. ✅ Deploy to cloud (AWS/GCP)
3. ✅ Set up monitoring
4. ✅ Write user documentation
5. ✅ Create deployment guide
6. ✅ MVP launch!

**Deliverable**: Production-ready MVP

---

### **Phase 5: Future Integration (Weeks 11+)**

#### Post-MVP: External System Integration
**Learning Focus**: API integration, Data synchronization

**Tasks**:
1. ✅ Implement ADP adapter
2. ✅ Build Cortex sync service
3. ✅ Create data reconciliation logic
4. ✅ Set up webhook handlers
5. ✅ Monitor integration health

**Deliverable**: Fully integrated system

---

## 🎓 Learning Checkpoints

### After Phase 1, you'll understand:
- FastAPI framework and async Python
- Database design and relationships
- Multi-tenancy architecture
- JWT authentication
- API design principles

### After Phase 2, you'll understand:
- Business logic implementation
- State machines
- Background job processing
- Testing strategies
- RBAC patterns

### After Phase 3, you'll understand:
- React and TypeScript
- State management patterns
- Mobile development with React Native
- API integration from frontend
- UX/UI design principles

### After Phase 4, you'll understand:
- DevOps and CI/CD
- Docker containerization
- Cloud deployment
- System monitoring
- Production best practices

---

## 🚀 Next Steps - Immediate Actions

### 1. Environment Setup (Today)
```bash
# Install prerequisites
brew install python@3.11 postgresql redis node

# Verify installations
python3 --version  # Should be 3.11+
psql --version     # Should be 15+
redis-cli --version
node --version     # Should be 18+
```

### 2. Start Phase 1 (Tomorrow)
- Set up backend project structure
- Configure database
- Build first endpoint

### 3. Weekly Check-ins
Every week we'll:
- Review what you learned
- Discuss challenges
- Plan next week's work
- Ensure understanding before moving forward

---

## ❓ Questions to Consider

Before we start coding:

1. **Development Environment**: Do you prefer Mac/Linux/WSL for development?
2. **Code Editor**: VS Code, PyCharm, or other?
3. **Time Commitment**: How many hours per week can you dedicate?
4. **Learning Style**: Prefer detailed explanations or learn by doing?

---

**Ready to start Phase 1: Backend Foundation?**
