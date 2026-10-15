"""ADR-514: a deploy rebuilds every service it starts.

Prod's deploy built `backend celery_worker` and started seven services, so
`celery_beat` and `bot` (each with its own `build:`) restarted on old images:
beat ran a 7-week-old schedule (20 of 35 jobs) and the bot 5-month-old code.
Nothing failed. Staging built all four, so staging never showed it.

Read from source, like tests/test_adr446_prod_bot_and_guild_map.py: the workflow
is YAML and runs on a remote host. PyYAML is not a backend dependency, so the
compose files are read as text.

The buildable services come from the COMPOSE FILES, not from a list in this
test: a new service with `build:` is covered without anyone editing this file.
"""
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
COMPOSE = [ROOT / "docker-compose.yml", ROOT / "docker-compose.prod.yml"]


def buildable_services() -> set[str]:
    """Services that declare `build:` in any compose file (2-space service indent)."""
    out: set[str] = set()
    for f in COMPOSE:
        current = None
        for line in f.read_text().splitlines():
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                current = m.group(1)
            elif current and re.match(r"^    build:", line):
                out.add(current)
    return out


def _services_after(cmd: str, verb: str) -> list[str]:
    """The service names after `<verb>` in one docker compose command."""
    words = shlex.split(cmd.split("&&")[-1])
    i = words.index(verb)
    return [w for w in words[i + 1:] if not w.startswith("-")]


def deploy_pairs() -> list[tuple[list[str], list[str]]]:
    """(built, started) for each deploy step that runs `up -d`."""
    lines = [ln.strip().strip('",') for ln in CI.read_text().splitlines()]
    pairs = []
    for i, ln in enumerate(lines):
        if "docker compose" in ln and " up -d " in ln:
            builds = [b for b in lines[max(0, i - 3):i] if "docker compose" in b and " build " in b]
            assert builds, f"deploy step starts services with no build command before it: {ln}"
            pairs.append((_services_after(builds[-1], "build"), _services_after(ln, "-d")))
    return pairs


def test_the_compose_files_are_read():
    # Guards the parser: if it found nothing, every later assertion would pass vacuously.
    assert {"backend", "celery_worker", "celery_beat", "bot"} <= buildable_services()


def test_both_environments_are_checked():
    assert len(deploy_pairs()) == 2, "expected staging and prod deploy steps (ADR-446, ADR-514)"


def test_every_started_service_that_builds_is_rebuilt():
    buildable = buildable_services()
    for built, started in deploy_pairs():
        stale = [s for s in started if s in buildable and s not in built]
        assert not stale, (
            f"started from an old image: {stale}. The step starts {started} but builds "
            f"only {built}; `up -d` reuses whatever image exists (ADR-514)."
        )
