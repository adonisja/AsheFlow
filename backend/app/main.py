from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app import models
from app.models.base import Base
from app.routers import employees, trucks, truck_assignments, assignment_members, employee_off_days, employee_relationships, dispatch, schedule, time_off_requests, feedback, training, notifications, field_ops, continuation_requests, assignment_change_requests, incidents, schedule_change_requests

# Alembic is now managing the database schema.
# We no longer need Base.metadata.create_all(bind=engine)

app = FastAPI(title="AsheFlow Dispatch API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://localhost:3004",
        "http://localhost:3005",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define our versioned API router
api_v1_router = APIRouter(prefix="/api/v1")

# Include all feature routers under the v1 prefix
api_v1_router.include_router(employees.router)
api_v1_router.include_router(trucks.router)
api_v1_router.include_router(truck_assignments.router)
api_v1_router.include_router(assignment_members.router)
api_v1_router.include_router(employee_off_days.router)
api_v1_router.include_router(employee_relationships.router)
api_v1_router.include_router(dispatch.router)
api_v1_router.include_router(schedule.router)
api_v1_router.include_router(time_off_requests.router)
api_v1_router.include_router(feedback.router)
api_v1_router.include_router(training.router)
api_v1_router.include_router(notifications.router)
api_v1_router.include_router(field_ops.router)
api_v1_router.include_router(continuation_requests.router)
api_v1_router.include_router(assignment_change_requests.router)
api_v1_router.include_router(incidents.router)
api_v1_router.include_router(schedule_change_requests.router)
# Mount the v1 router to the main app
app.include_router(api_v1_router)

@app.get("/health")
def health_check():
    """Return a simple liveness check response.

    Returns:
        A dict with key ``"status"`` set to ``"ok"``.
    """
    return {"status": "ok"}
