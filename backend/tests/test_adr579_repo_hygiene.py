"""ADR-579: the OCR engine ships with every deploy, station data never enters
the repo, and the iOS app is com.asheflow.mobile.
"""
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CI = (ROOT / ".github/workflows/ci.yml").read_text()


def _ignored(path: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT)
    return r.returncode == 0


class TestTheOcrEngineShips:
    @pytest.mark.parametrize("env", ["staging", "prod"])
    def test_it_is_vendored_before_each_frontend_build(self, env):
        build = CI.index(f"- name: Build frontend ({env})")
        vendor = CI.rfind("run: bash scripts/vendor-tesseract.sh", 0, build)
        npm_ci = CI.rfind("run: npm ci", 0, build)
        assert vendor != -1 and npm_ci < vendor < build, (
            f"the {env} build must run vendor-tesseract.sh after npm ci and before "
            "the build, or /tesseract/* falls through to index.html (ADR-579)")

    def test_the_downloaded_language_data_is_pinned(self):
        src = (ROOT / "scripts/vendor-tesseract.sh").read_text()
        assert re.search(r'LANG_SHA256="[0-9a-f]{64}"', src), "language data checksum not pinned"
        assert "exit 1" in src.split("LANG_SHA256", 1)[1], "a checksum mismatch must fail the build"


class TestStationDataStaysOut:
    @pytest.mark.parametrize("name", [
        "NYCD_2026-09-09_08-02.xlsx",
        "nycd_btr_explore.ipynb",
        "DSP_Overview_Dashboard_Trailing_Six_Week_NYCD_DJZ3_2026-W38_edited.csv",
        "drop_column.ipynb",
        "analysis/.ipynb_checkpoints/x-checkpoint.ipynb",
    ])
    def test_it_is_ignored(self, name):
        assert _ignored(name), f"{name} would be committable (ADR-579)"

    @pytest.mark.parametrize("name", [
        "backend/tests/fixtures/btr_workbook_day1.xlsx",
        "backend/app/routers/scorecards.py",
        "frontend/src/components/ScorecardCard.tsx",
    ])
    def test_the_rules_leave_real_files_alone(self, name):
        assert not _ignored(name), f"{name} is caught by a station-data rule"

    def test_no_station_file_is_tracked(self):
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                                 text=True, check=True).stdout.splitlines()
        assert not [p for p in tracked if re.search(r"nycd[_-]|\.ipynb$", p, re.I)]


def test_the_ios_app_is_com_asheflow_mobile():
    pbx = (ROOT / "mobile/ios/AsheFlowMobile.xcodeproj/project.pbxproj").read_text()
    ids = re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", pbx)
    assert ids and set(ids) == {"com.asheflow.mobile"}, ids
