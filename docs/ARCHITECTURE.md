# AsheFlow Architecture Documentation

## System Architecture Overview

AsheFlow is built as a multi-tenant B2B SaaS platform with a microservices-oriented monolithic architecture, designed to scale horizontally as the business grows.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Applications                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Web App     │  │  Mobile App  │  │  Admin Panel │      │
│  │  (React)     │  │(React Native)│  │   (React)    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      API Gateway / Load Balancer             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Backend Services (FastAPI)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │     Auth     │  │   Crew Mgmt  │  │ Time Tracking│      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Logistics   │  │   Payroll    │  │  Reporting   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
┌─────────────────────────┐  ┌─────────────────────────┐
│    PostgreSQL Database  │  │    Redis Cache/Queue    │
└─────────────────────────┘  └─────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────┐
│                    Celery Workers                            │
│  (Background tasks, payroll, notifications, reports)         │
└─────────────────────────────────────────────────────────────┘
```

## Multi-Tenancy Design

### Strategy: Shared Database with Tenant Isolation

Every table includes a `tenant_id` (company_id) column to ensure data isolation.

**Key Benefits:**
- Cost-effective for scaling
- Easier maintenance
- Simplified backups

**Security Measures:**
- Row-Level Security (RLS) in PostgreSQL
- Middleware-level tenant validation
- Tenant context in all queries

### Data Model Structure

```python
# Every model inherits from TenantBase
class TenantBase:
    tenant_id: UUID
    created_at: DateTime
    updated_at: DateTime
    is_active: Boolean
```

## Core Modules

### 1. Authentication & Authorization

**Technologies:**
- OAuth2 with Password Flow (and Bearer tokens)
- JWT tokens (Access + Refresh)
- Password hashing with bcrypt

**User Roles:**
- `super_admin` - Platform administrator
- `company_admin` - Company owner/manager
- `manager` - Team/crew manager
- `driver` - Delivery associate
- `dispatcher` - Logistics coordinator

**Permissions:**
- Role-based access control (RBAC)
- Resource-level permissions
- Tenant-specific permissions

### 2. Crew Management

**Features:**
- Employee profiles (personal info, emergency contacts)
- Team/crew assignments
- Vehicle assignments
- Document management (licenses, certifications)
- Performance tracking

**Database Tables:**
- `employees`
- `teams`
- `employee_documents`
- `vehicle_assignments`

### 3. Time Management

**Features:**
- Clock in/out (GPS-tracked)
- Timesheet management
- Break tracking
- Overtime calculation
- Schedule management
- Leave requests and approvals

**Database Tables:**
- `time_entries`
- `schedules`
- `leave_requests`
- `overtime_records`

### 4. Logistics

**Features:**
- Route planning and optimization
- Delivery assignments
- Real-time tracking
- Vehicle management
- Delivery status updates
- Proof of delivery

**Database Tables:**
- `routes`
- `deliveries`
- `vehicles`
- `delivery_status_log`
- `proof_of_delivery`

### 5. Payroll

**Features:**
- Automated wage calculation
- Deductions management
- Tax calculations
- Pay period management
- Payment history
- Export to accounting systems

**Database Tables:**
- `pay_periods`
- `payroll_records`
- `deductions`
- `tax_configurations`

### 6. Reporting & Analytics

**Features:**
- Dashboard metrics
- Performance reports
- Financial reports
- Custom report builder
- Export capabilities (PDF, Excel)
- Scheduled reports

## API Design

### RESTful Principles

```
/api/v1/
  /auth/
    POST   /register
    POST   /login
    POST   /refresh
    POST   /logout
  /companies/
    GET    /
    POST   /
    GET    /{id}
    PUT    /{id}
    DELETE /{id}
  /employees/
    GET    /
    POST   /
    GET    /{id}
    PUT    /{id}
    DELETE /{id}
  /time-entries/
    GET    /
    POST   /clock-in
    POST   /clock-out
    GET    /{id}
  /deliveries/
    GET    /
    POST   /
    GET    /{id}
    PUT    /{id}/status
  /payroll/
    GET    /periods
    POST   /calculate
    GET    /{id}
```

### Response Format

```json
{
  "success": true,
  "data": {},
  "message": "Success message",
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 100
  }
}
```

## Database Schema Design

### Core Principles

1. **Multi-tenancy**: All tables have `tenant_id`
2. **Soft deletes**: Use `is_active` or `deleted_at`
3. **Audit trails**: `created_at`, `updated_at`, `created_by`, `updated_by`
4. **UUID Primary Keys**: Better for distributed systems
5. **Indexes**: On foreign keys and frequently queried columns

### Key Relationships

```
companies (tenants)
  ├── employees
  │     ├── time_entries
  │     ├── deliveries
  │     ├── payroll_records
  │     └── employee_documents
  ├── teams
  ├── vehicles
  ├── routes
  └── pay_periods
```

## Security Architecture

### Authentication Flow

1. User logs in with email/password
2. Backend validates credentials
3. JWT access token (15 min) + refresh token (7 days) issued
4. Client stores tokens securely
5. Access token sent in Authorization header
6. Token refreshed when expired

### Data Security

- **Encryption at rest**: Database-level encryption
- **Encryption in transit**: HTTPS/TLS
- **Password hashing**: Bcrypt with salt
- **Secret management**: Environment variables/AWS Secrets Manager
- **SQL injection prevention**: ORM parameterized queries
- **XSS prevention**: Input sanitization
- **CSRF protection**: Token-based validation

### Tenant Isolation

```python
# Middleware ensures tenant context
async def tenant_middleware(request: Request, call_next):
    tenant_id = get_tenant_from_token(request)
    request.state.tenant_id = tenant_id
    response = await call_next(request)
    return response

# All queries auto-filter by tenant
query = db.query(Employee).filter(
    Employee.tenant_id == request.state.tenant_id
)
```

## Scalability Strategy

### Horizontal Scaling

- Stateless API servers
- Load balancer distribution
- Database read replicas
- Redis caching layer

### Performance Optimization

- Database indexing
- Query optimization
- Caching strategies (Redis)
- Pagination for large datasets
- Async operations with Celery
- CDN for static assets

### Monitoring & Observability

- Application metrics (Prometheus)
- Log aggregation (ELK/CloudWatch)
- Distributed tracing
- Error tracking (Sentry)
- Uptime monitoring

## Technology Stack Rationale

### Why FastAPI?
- High performance (async)
- Auto-generated documentation
- Type hints and validation
- Modern Python features
- Great for APIs

### Why PostgreSQL?
- ACID compliance
- JSON support (JSONB)
- Row-level security
- Mature and reliable
- Excellent for multi-tenancy

### Why Redis?
- Fast caching
- Message broker for Celery
- Session storage
- Rate limiting

### Why React?
- Component reusability
- Large ecosystem
- React Native code sharing
- Strong community support

## Deployment Architecture

### Development
- Docker Compose locally
- Hot reload for development

### Staging
- AWS ECS/EKS or GCP Cloud Run
- Managed database (RDS/Cloud SQL)
- Managed Redis (ElastiCache)

### Production
- Multi-region deployment
- Auto-scaling groups
- Database backups
- Disaster recovery plan
- Blue-green deployments

## Future Considerations

- Microservices split (if needed at scale)
- GraphQL API layer
- ML for route optimization
- Real-time notifications (WebSockets)
- Mobile offline support
- Multi-language support
