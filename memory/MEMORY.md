# Memory Index

- [Admin role scope](feedback_admin_role.md) — Admins have full access to everything; never describe access as manager-only without including admin
- [Fix logging workflow](feedback_fix_logging.md) — Every fix requires: ADR in docs/decisions/, section in docs/LEARNING_GUIDE.md, journal in docs/journals/
- [Sort pipeline design](project_sort_pipeline_design.md) — Canonical field decisions, enriched package dict structure, OV pairing derivation, pipeline flow corrections, 14-item gap list. Updated 2026-06-24.
- [BuildingProfile system design](project_building_profile_design.md) — COMPLETE 2026-06-24: address-level delivery intelligence, weighted route scoring, two routers built, LocationProfile dropped. ADR-135. 2 open gaps.
- [Second wave & injury status design](project_wave_injury_design.md) — ADR-139 design accepted 2026-06-25. wave_number on Route, injury_status on Employee, back-at-truck event split, wave pool endpoint, auto-assign proposal mode. Implementation pending.
- [RTS / handoff / reattempt design](project_rts_handoff_reattempt_design.md) — ADR-141 accepted 2026-06-25. RTSPackage, MissingPackage, RouteHandoff, ReattemptAssignment. RTSReport becomes server-computed. BuildingProfile/Library gain operating hours. Implementation not started.
- [Gap list 2026-06-26](project_gap_list_2026_06_26.md) — 15-item workflow gap list; confirmed design decisions (tag_number in enriched dict, OV zones as list[dict], ArrivalConfirmResponse fix, MisroutedPackageOut id field, normalised_addresses on Route, tote reassignment endpoint, NextStopSuggestion bag grouping). IN PROGRESS.
