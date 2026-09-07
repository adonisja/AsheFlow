"""Two hand-maintained lists that nothing keeps in step (ADR-395).

Both are duplications the codebase accepted deliberately, and both fail SILENTLY
when they drift:

  1. The ADR-390 permission probe vs the calls mfa_containment.contain() makes.
     A call the probe does not cover can lose its IAM grant and nothing notices
     until a human clicks Reset -- which is exactly how ADR-389 happened.

  2. FAV_LIMITS in Preferences.tsx vs employee_relationships.py. The client caps
     what the picker offers; the server enforces. If the client is more generous
     the user is refused after choosing, which is the 409-after-the-fact UX
     ADR-383 set out to remove.
"""
import inspect
import re
from pathlib import Path

from app.services import mfa_containment
from app.tasks import security_infra_health

REPO = Path(__file__).resolve().parents[3]


class TestThePermissionProbeCoversEveryContainmentCall:
    def test_no_containment_call_is_unprobed(self):
        """ADR-390's probe verifies we are still ALLOWED to run containment. A
        call it does not cover is a permission that can be revoked silently.

        Found real drift when written: contain() gained admin_get_user (ADR-392)
        and admin_forget_device was never probed.
        """
        src = inspect.getsource(mfa_containment.contain)
        called = set(re.findall(r"client\.(admin_\w+)\(", src))

        probe_src = inspect.getsource(
            security_infra_health._check_containment_permissions)
        # Compare on the boto3 METHOD the probe actually invokes, not on its
        # display label. A PascalCase->snake_case conversion is wrong for names
        # like AdminSetUserMFAPreference, where the acronym does not split.
        probed = set(re.findall(r"client\.(admin_\w+)\(", probe_src))

        missing = called - probed
        assert not missing, (
            f"contain() calls {sorted(missing)} but the ADR-390 probe does not "
            "check permission for them. A revoked grant on any of these fails "
            "only when a human clicks Reset."
        )


class TestTheFavLimitsMirrorMatchesTheServer:
    """ADR-383 mirrored FAV_LIMITS into the client so the picker can show caps
    before a 409. There is no codegen, so the two can drift."""

    def _parse(self, text: str, brace: str) -> dict:
        # Both files write the same shape: role -> {target: int}.
        body = text[text.index(brace):]
        depth, end = 0, 0
        for i, ch in enumerate(body):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        out = {}
        for role, inner in re.findall(r'["\']?(\w+)["\']?\s*:\s*\{([^}]*)\}', body[:end + 1]):
            caps = {
                k: int(v)
                for k, v in re.findall(r'["\']?(\w+)["\']?\s*:\s*(\d+)', inner)
            }
            if caps:
                out[role] = caps
        return out

    def test_client_and_server_tables_are_identical(self):
        server = self._parse(
            (REPO / "backend/app/routers/employee_relationships.py").read_text(),
            "FAV_LIMITS = {",
        )
        client = self._parse(
            (REPO / "frontend/src/pages/Preferences.tsx").read_text(),
            "FAV_LIMITS: Record<string, Record<string, number>> = {",
        )
        assert server, "could not parse the server table"
        assert client, "could not parse the client table"
        assert client == server, (
            "FAV_LIMITS drifted. The client caps what the picker offers and the "
            "server enforces; if the client is more generous the user is refused "
            "after choosing, which is what ADR-383 removed.\n"
            f"server={server}\nclient={client}"
        )
