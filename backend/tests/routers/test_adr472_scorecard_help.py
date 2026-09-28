"""Teach the metric, not the threshold (ADR-472).

42 fields on the Owner setup page, 10 with no help entry -- all ten the Amazon
scorecard targets, which are the fields most in need of it: DCR, POD, DSB and
DVIC are Amazon's vocabulary, not ours, and their directions are inconsistent.

Drafted from public research, then checked against Amazon's own metric guides
supplied by the tenant. FIVE of the ten did not match the metric they are named
after. Realigning them is ADR-473; these tests pin what the help may say in the
meantime.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
DRAWER = ROOT / "frontend/src/components/ui/SettingsHelpDrawer.tsx"
SETTINGS = ROOT / "frontend/src/pages/CompanySettings.tsx"

# Correct shape, verified against Amazon's guides.
VERIFIED = [
    "scorecard_pod_target",
    "scorecard_dsb_dpmo_target",
    "scorecard_fico_target",
    "scorecard_speeding_rate_target",
    "scorecard_signsignal_rate_target",
]
# Shape does not match the real metric. ADR-473.
PROVISIONAL = [
    "scorecard_dcr_target",
    "scorecard_cdf_target",
    "scorecard_cc_target",
    "scorecard_dnr_dpmo_target",
    "scorecard_dvic_target",
]


def _entry(key: str) -> str:
    src = DRAWER.read_text()
    i = src.index(f"  {key}: {{")
    return src[i:src.index("\n  },", i)]


# ── coverage ────────────────────────────────────────────────────────────────

def test_every_setup_field_has_help():
    """The audit that started this ADR, as a test so it cannot regress."""
    cs = SETTINGS.read_text()
    keys = set(re.findall(r"^\s{2}([a-z0-9_]+):\s*\{", DRAWER.read_text(), re.M))
    groups = ["SHIFT_TIMING", "TRAINING_RULES", "WALKER_RATING", "ATTENDANCE",
              "EFFORT_SCORING", "SCORECARD_QUALITY", "SCORECARD_SAFETY",
              "INGESTION", "DISCORD_CHANNELS", "DISCORD_ROLES"]
    missing = []
    for g in groups:
        m = re.search(rf"const {g}[^=]*=\s*\[(.*?)\n\];", cs, re.S)
        if not m:
            continue
        for f in re.findall(r"key:\s*'([a-z0-9_]+)'", m.group(1)):
            if f not in keys:
                missing.append(f)
    assert not missing, f"fields with no help entry: {missing}"


# ── D1: no thresholds ───────────────────────────────────────────────────────

def test_no_amazon_threshold_figures_appear():
    """Amazon revises these. A number frozen here reads as authoritative and
    goes stale silently -- the dashboard fabrication failure, restated.

    The guides' actual Fantastic figures are checked for by value.
    """
    src = DRAWER.read_text()
    block = src[src.index("Amazon scorecard targets (ADR-472)"):
                src.index("ncns_cutoff_minutes:")]
    # Strip the `example:` lines -- an illustrative value is the point of those,
    # and they are explicitly labelled as examples in the UI.
    prose = "\n".join(l for l in block.splitlines() if "example:" not in l)
    for figure in ("233", "429", "980", "1115", "3900", "3,900", "2000"):
        assert figure not in prose, (
            f"the threshold {figure} is stated in the drawer prose"
        )


def test_every_verified_entry_points_at_the_tenants_own_scorecard():
    for key in VERIFIED:
        assert "your own weekly scorecard" in _entry(key), (
            f"{key} does not tell the Owner where the number comes from"
        )


# ── D2: understanding, not reproduction ─────────────────────────────────────

def test_the_facts_that_only_the_guides_could_give():
    """These distinguish guide-sourced help from research-sourced help. If an
    edit loses them, the entry has drifted back to generic advice."""
    pod = _entry("scorecard_pod_target")
    assert "RETAKING" in pod and "SKIPPING" in pod, (
        "the retake-vs-skip rule is the single most coachable POD fact"
    )

    sign = _entry("scorecard_signsignal_rate_target")
    assert "U-turn" in sign, "illegal U-turns are in this metric and easily missed"
    assert "ALREADY red" in sign, "the already-red vs entered-on-yellow distinction"

    fico = _entry("scorecard_fico_target")
    assert "SMALLEST" in fico, (
        "FICO reads as the headline safety number and is the smallest input"
    )

    speed = _entry("scorecard_speeding_rate_target")
    assert "a DAY on which they delivered" in speed, (
        "a trip is a day, not a route -- two routes in one day count once"
    )


def test_dsb_explains_that_dnr_sits_inside_it():
    dsb = _entry("scorecard_dsb_dpmo_target")
    assert "INSIDE" in dsb and "DNR" in dsb.upper()


# ── D3: provisional entries stay honest and short ───────────────────────────

def test_each_provisional_field_tells_the_owner_to_leave_it_blank():
    """They do not match the metric they are named after, and nothing compares
    against them yet, so blank is correct and costs nothing."""
    for key in PROVISIONAL:
        e = _entry(key)
        assert "Leave this blank" in e, f"{key} does not say to leave it blank"
        assert "noteTone: 'warning'" in e, f"{key} is not visually flagged"


def test_provisional_entries_do_not_explain_behaviour_that_is_changing():
    """No `example` value: offering one would suggest a shape we are about to
    change, which is exactly what makes documenting a defect worse than
    documenting nothing."""
    for key in PROVISIONAL:
        assert "example:" not in _entry(key), (
            f"{key} offers an example value for a field whose shape is wrong"
        )


def test_the_verified_entries_do_carry_examples():
    """The complement: a field with the right shape should show what a value
    looks like."""
    for key in VERIFIED:
        assert "example:" in _entry(key)


# ── D4: no empty section ────────────────────────────────────────────────────

def test_the_empty_dispatch_weights_section_is_gone():
    """A titled card with no contents reads as a loading failure on the first
    page an Owner ever sees."""
    cs = SETTINGS.read_text()
    assert "DISPATCH_WEIGHTS" not in cs


def test_no_config_section_is_empty():
    """The general form, so the next emptied section is caught too."""
    cs = SETTINGS.read_text()
    block = cs.split("const CONFIG_SECTIONS", 1)[1].split("];", 1)[0]
    for name in re.findall(r"fields:\s*([A-Z_]+)", block):
        m = re.search(rf"const {name}[^=]*=\s*\[(.*?)\n\];", cs, re.S)
        assert m and "key:" in m.group(1), (
            f"section {name} renders a title with no fields"
        )
