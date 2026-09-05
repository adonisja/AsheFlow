"""Request bodies refuse what they do not declare, and derivation is bounded (ADR-380 D4/D5).

D4 — four request schemas in schemas/employee.py had no `extra="forbid"`, so
Pydantic silently DROPPED unknown keys. Found by auditing the module rather than
fixing the one that surfaced:

    EmployeeCreate          ignore   <- found first
    EmployeeUpdate          ignore   <- larger blast radius
    InjuryStatusPatch       ignore
    BulkImportRow           ignore
    RoleTransitionRequest   forbid   <- the only one already correct

Not exploitable -- `model_dump()` emits only declared fields, so extras never
reach the ORM. The damage is silence: `is_active=True` on a create was accepted
and ignored rather than refused, and on EmployeeUpdate (every field optional) an
entirely misspelled body was a successful no-op the caller believed had worked.

D5 — `_derive_username` looped `while` with no cap.
"""
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.registration import _derive_username
from app.schemas.employee import (
    BulkImportRow,
    EmployeeCreate,
    EmployeePublicResponse,
    EmployeeResponse,
    EmployeeUpdate,
    InjuryStatusPatch,
    RoleTransitionRequest,
)

REQUEST_SCHEMAS = [
    EmployeeCreate, EmployeeUpdate, InjuryStatusPatch,
    BulkImportRow, RoleTransitionRequest,
]
RESPONSE_SCHEMAS = [EmployeeResponse, EmployeePublicResponse]


class TestEveryRequestSchemaForbidsExtras:
    @pytest.mark.parametrize("schema", REQUEST_SCHEMAS, ids=lambda s: s.__name__)
    def test_it_declares_forbid(self, schema):
        assert schema.model_config.get("extra") == "forbid", (
            f"{schema.__name__} is a REQUEST body; without extra='forbid' an "
            f"unknown key is silently dropped instead of refused (D9)"
        )

    def test_a_create_cannot_smuggle_is_active(self):
        """The concrete case. is_active is hardcoded False by the endpoint; a
        caller setting it was silently ignored rather than told no."""
        with pytest.raises(ValidationError):
            EmployeeCreate(
                name="New Hire", email="new@hire.com", role="trainee",
                is_active=True,
            )

    def test_a_misspelled_update_field_is_refused_not_ignored(self):
        """Every EmployeeUpdate field is optional, so a typo produced NO error:
        the request succeeded, changed nothing, and looked like it worked."""
        with pytest.raises(ValidationError):
            EmployeeUpdate(nmae="Typo")

    def test_a_bulk_row_with_a_stray_column_is_refused(self):
        """A mis-mapped CSV column is exactly the case that goes unnoticed:
        200 rows import 'successfully' with a whole column discarded."""
        with pytest.raises(ValidationError):
            BulkImportRow(
                name="A", email="a@b.com", role="trainee", employee_id="x",
            )

    def test_an_injury_patch_with_a_stray_key_is_refused(self):
        with pytest.raises(ValidationError):
            InjuryStatusPatch(injury_status="injured", notes="hurt")

    @pytest.mark.parametrize("schema", RESPONSE_SCHEMAS, ids=lambda s: s.__name__)
    def test_response_schemas_are_left_alone(self, schema):
        """The Dimension 9 rule is scoped to the TRUST BOUNDARY. `extra` on a
        response model is a typing weakness, not an injection surface, and
        forbidding it there breaks from_attributes round-trips for no gain."""
        assert schema.model_config.get("extra") != "forbid"

    def test_valid_bodies_still_parse(self):
        """The guard must refuse only what is undeclared."""
        assert EmployeeCreate(
            name="Real Hire", email="real@hire.com", role="driver_trainee",
        ).role == "driver_trainee"
        assert EmployeeUpdate(name="Renamed").name == "Renamed"


class TestUsernameDerivationIsBounded:
    def test_it_raises_rather_than_spinning(self):
        """Every candidate taken. 100 employees sharing one normalised name in a
        single Cognito pool is a bug or an attack, not a roster."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = object()

        with pytest.raises(HTTPException) as exc:
            _derive_username("Jane Smith", db)
        assert exc.value.status_code == 502

    def test_the_normal_path_is_unchanged(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        assert _derive_username("Jane Smith", db) == "jane.smith"

    def test_it_still_suffixes_on_a_real_collision(self):
        """Bounding must not break the behaviour the loop exists for."""
        # First candidate taken, second free.
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [object(), None]
        assert _derive_username("Jane Smith", db) == "jane.smith2"

    def test_the_cap_is_not_reached_by_a_plausible_roster(self):
        """A handful of collisions must still resolve normally."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = (
            [object()] * 5 + [None]
        )
        assert _derive_username("Jane Smith", db) == "jane.smith6"
