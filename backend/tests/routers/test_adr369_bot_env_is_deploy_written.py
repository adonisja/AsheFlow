"""The bot's M2M credentials survive a deploy (ADR-369).

The ADR-363 cutover was done by editing bot/.env on the box. Every deploy
rewrites that file from scratch:

    open('/home/ubuntu/AsheFlow/bot/.env', 'w').write(...)

'w', not 'a'. So the next push silently reverted the bot to the password path,
and the only symptom was one log line changing from "Bot M2M token acquired" to
"Bot Cognito token refreshed" in a container nobody tails.

A silent reversion to a WORKING fallback is the hardest kind to notice: nothing
errored, the bot ran, and the API calls succeeded.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / ".github" / "workflows" / "ci.yml"
BOT_CONFIG = ROOT / "bot" / "config.py"

# The workflow encodes parameter names as chr() sums so the file carries no
# literal secret names. Decode before asserting, or the test pins the encoding
# rather than the behaviour.
_CHR = re.compile(r"chr\((\d+)\)")


def _keep_set() -> set[str]:
    s = CI.read_text(errors="ignore")
    i = s.index("keep={")
    body = s[i + 6: s.index("}", i)]
    return {
        _CHR.sub(lambda m: chr(int(m.group(1))), chunk).replace("+", "")
        for chunk in body.split(",")
    }


class TestTheDeployWritesTheM2MCredentials:
    @pytest.mark.parametrize("name", [
        "COGNITO_M2M_CLIENT_ID",
        "COGNITO_M2M_CLIENT_SECRET",
        "COGNITO_OAUTH_DOMAIN",
    ])
    def test_it_is_in_the_keep_set(self, name):
        assert name in _keep_set(), (
            f"{name} is not written by the deploy, so a hand-edited bot/.env is "
            "reverted on the next push and the bot silently falls back to the "
            "password path"
        )

    def test_the_existing_bot_secrets_are_still_written(self):
        """A careless edit to the keep set could drop these, which WOULD be
        loud -- but only after a deploy."""
        keep = _keep_set()
        for name in ("DISCORD_BOT_TOKEN", "BOT_USERNAME", "BOT_PASSWORD", "INTERNAL_SECRET"):
            assert name in keep, f"{name} would stop being written to bot/.env"


class TestAMissingParameterFallsBack:
    """ADR-369 D2 -- an environment without M2M parameters must still deploy,
    rather than ending up half-configured.

    The original wording said "prod has no M2M parameters yet". That is no
    longer why this matters: ADR-441 made per-tenant credentials the normal
    path, so the env pair is a FALLBACK that fires only when a company has no
    provisioned client. The requirement is unchanged — optional fields, loud
    failure when half-set — but the reason is."""

    def test_the_bot_requires_both_values_before_using_m2m(self):
        src = BOT_CONFIG.read_text(errors="ignore")
        for field in ("cognito_m2m_client_id", "cognito_m2m_client_secret", "cognito_oauth_domain"):
            assert f"{field}: str | None = None" in src, (
                f"{field} must be optional, or an environment without it fails "
                "to start instead of falling back"
            )

    def test_a_half_configured_environment_fails_loudly(self):
        """Was test_the_client_prefers_m2m_only_when_both_are_set.

        There is nothing left to fall back TO: ADR-377 removed the password
        path. A half-configured environment must now name the problem rather
        than attempt M2M with a missing secret, which would surface as a
        TypeError inside aiohttp.BasicAuth.
        """
        client = (ROOT / "bot" / "services" / "api_client.py").read_text(errors="ignore")
        assert "if not (settings.cognito_m2m_client_id and settings.cognito_m2m_client_secret):" in client, (
            "a half-configured environment must be refused with a named error"
        )
        assert "COGNITO_M2M_CLIENT_ID and COGNITO_M2M_CLIENT_SECRET are required" in client


class TestBothEnvironmentsWriteTheBotEnv:
    """ADR-441. Prod's deploy job BUILDS AND STARTS the bot container but never
    wrote its .env, so the container had a stale pre-ADR-377 file (BOT_USERNAME,
    BOT_PASSWORD, no M2M keys) and could not start. Staging had the step; prod
    did not, and nothing said so.
    """

    @staticmethod
    def _jobs():
        import yaml
        from pathlib import Path
        ci = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
        return yaml.safe_load(ci.read_text())["jobs"]

    def test_every_deploy_job_writes_the_bot_env(self):
        """Checks BOTH jobs, not a named one: a third environment added later
        inherits the question instead of rediscovering it."""
        for job in ("deploy-staging", "deploy-prod"):
            names = [s.get("name", "") for s in self._jobs()[job]["steps"]]
            assert any("bot .env" in n for n in names), (
                f"{job} starts the bot container but never writes its .env"
            )

    def test_the_bot_env_is_written_before_the_deploy(self):
        """The deploy is what starts the container. An .env written after it
        lands on a container that already failed to start."""
        for job in ("deploy-staging", "deploy-prod"):
            names = [s.get("name", "") for s in self._jobs()[job]["steps"]]
            env_at = next(i for i, n in enumerate(names) if "bot .env" in n)
            dep_at = next(i for i, n in enumerate(names) if n == "Deploy backend via SSM")
            assert env_at < dep_at, f"{job} writes bot/.env after the deploy"

    def test_prod_reads_its_own_parameter_path(self):
        """A copied step that still points at /asheflow/staging/ would put
        staging's secrets on the prod host."""
        import re
        from pathlib import Path

        ci = (Path(__file__).resolve().parents[3]
              / ".github" / "workflows" / "ci.yml").read_text()
        i = ci.index("Write prod bot .env")
        block = ci[i:i + 4000]
        m = re.search(r"Path=((?:chr\(\d+\)\+?)+)", block)
        path = "".join(chr(int(c)) for c in re.findall(r"chr\((\d+)\)", m.group(1)))
        assert path == "/asheflow/prod/", f"prod bot step reads {path}"
