# Journal: Feedback Admin UI
**Date:** 2026-04-16

---

## Context

The feedback system (`FeedbackModal` → `POST /feedback/`) had no admin review surface. Submitted feedback was stored in the DB with no way to triage or update its status from the application. `GET /feedback/` was also incorrectly gated to `management` + `admin` — management has no operational stake in bug reports or feature requests.

---

## Changes Applied

---

### Backend — `backend/app/routers/feedback.py`

**1. Restricted `GET /feedback/` to admin only.**  
Changed `RoleChecker(["management", "admin"])` to `allow_admin = RoleChecker(["admin"])`.

**2. Added `PATCH /feedback/{id}/status` endpoint (admin only).**  
Accepts `{ status: str }`. Validates against `_VALID_STATUSES = {"new", "in_progress", "resolved"}`. Returns 422 on invalid value, 404 if record not found, updated `FeedbackResponse` on success.

```python
@router.patch("/{feedback_id}/status", response_model=FeedbackResponse)
def update_feedback_status(feedback_id, payload, _=Depends(allow_admin), db=Depends(get_db)):
    ...
    record.status = payload.status
    db.commit()
```

---

### Backend — `backend/app/schemas/feedback.py`

**3. Added `FeedbackStatusUpdate` schema.**

```python
class FeedbackStatusUpdate(BaseModel):
    status: str
```

---

### Frontend — `frontend/src/pages/AdminDashboard.tsx`

**4. Added `Feedback` type and `feedback` / `feedbackFilter` state.**

**5. Added `GET /feedback/?limit=200` to `fetchAll` `Promise.allSettled` fan-out.**

**6. Added `handleUpdateFeedbackStatus` handler.**  
Calls `PATCH /feedback/{id}/status`, updates local state on success.

**7. Added Feedback Inbox section to the JSX** (placed above the Truck Fleet section).  
Features:
- Filter tabs: All / New / In Progress / Resolved
- Per-item: type badge (Bug/Feature Request/General with icon), status badge (color-coded), age badge (danger ≥7d, warning 3–6d, neutral otherwise)
- Action buttons per item: "In Progress" (when not in_progress), "Resolve" (when not resolved), "Reopen" (when resolved)
- Empty states for no feedback and no matching filter
- Scrollable list (max-h-[480px]) to keep the dashboard page length reasonable

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/feedback.py` | Restrict GET to admin; add PATCH status endpoint |
| `backend/app/schemas/feedback.py` | Add `FeedbackStatusUpdate` schema |
| `frontend/src/pages/AdminDashboard.tsx` | Add Feedback type, state, fetch, handler, and Inbox section |
