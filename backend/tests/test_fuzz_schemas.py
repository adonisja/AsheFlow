"""
Property-based fuzz tests using Hypothesis.

These tests verify that schema validation rejects arbitrary invalid input —
not just the specific bad values a developer thought of. Hypothesis generates
hundreds of random inputs per run, finding edge cases like empty strings,
Unicode, null bytes, and very long strings automatically.

Run with: python -m pytest tests/test_fuzz_schemas.py -v
"""
import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.feedback import FeedbackCreate, FeedbackStatusUpdate
from app.schemas.truck import TruckCreate, TruckUpdate
from app.schemas.employee import EmployeeCreate

VALID_FEEDBACK_TYPES = {"bug", "feature_request", "general"}
VALID_FEEDBACK_STATUSES = {"new", "in_progress", "resolved"}


class TestFeedbackCreateFuzz:
    @given(st.text().filter(lambda s: s not in VALID_FEEDBACK_TYPES))
    @h_settings(max_examples=200)
    def test_invalid_type_always_rejected(self, invalid_type: str):
        """Any string outside the allow-list must raise ValidationError."""
        with pytest.raises(ValidationError):
            FeedbackCreate(type=invalid_type, message="hello")

    @given(st.sampled_from(sorted(VALID_FEEDBACK_TYPES)))
    def test_valid_type_always_accepted(self, valid_type: str):
        """Every member of the allow-list must be accepted."""
        obj = FeedbackCreate(type=valid_type, message="hello")
        assert obj.type == valid_type

    @given(st.text(min_size=2001))
    def test_message_over_max_length_rejected(self, long_message: str):
        """Messages longer than 2000 characters must be rejected."""
        with pytest.raises(ValidationError):
            FeedbackCreate(type="bug", message=long_message)


class TestFeedbackStatusUpdateFuzz:
    @given(st.text().filter(lambda s: s not in VALID_FEEDBACK_STATUSES))
    @h_settings(max_examples=200)
    def test_invalid_status_always_rejected(self, invalid_status: str):
        """Any string outside the status allow-list must raise ValidationError."""
        with pytest.raises(ValidationError):
            FeedbackStatusUpdate(status=invalid_status)

    @given(st.sampled_from(sorted(VALID_FEEDBACK_STATUSES)))
    def test_valid_status_always_accepted(self, valid_status: str):
        """Every valid status must be accepted."""
        obj = FeedbackStatusUpdate(status=valid_status)
        assert obj.status == valid_status


class TestTruckCreateFuzz:
    @given(st.text(min_size=101))
    def test_name_over_max_length_rejected(self, long_name: str):
        """Truck names longer than 100 characters must be rejected."""
        with pytest.raises(ValidationError):
            TruckCreate(name=long_name)

    @given(st.just(""))
    def test_empty_name_rejected(self, empty: str):
        """Empty truck name must be rejected (min_length=1)."""
        with pytest.raises(ValidationError):
            TruckCreate(name=empty)

    @given(st.text(min_size=1, max_size=100))
    def test_valid_name_accepted(self, name: str):
        """Any non-empty string up to 100 chars must be accepted."""
        obj = TruckCreate(name=name)
        assert obj.name == name


class TestEmployeeCreateFuzz:
    @given(st.text().filter(lambda s: "@" not in s or "." not in s.split("@")[-1]))
    @h_settings(max_examples=200)
    def test_invalid_email_always_rejected(self, invalid_email: str):
        """Strings that are clearly not emails must be rejected by EmailStr."""
        with pytest.raises(ValidationError):
            EmployeeCreate(
                name="Test User",
                email=invalid_email,
                role="driver",
                username="testuser",
            )
