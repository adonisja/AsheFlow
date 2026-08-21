"""Manifest ingestor — the TBA-column contract behind the upload guards.

The upload endpoint rejects a file that parses to zero VALID packages (all rows
pending) with a "did you upload an enriched export?" hint. That guard relies on
this behavior: rows without an exact "Tracking ID" column all become pending.
"""
from app.services.manifest_ingestor import APIManifestIngestor


def test_raw_manifest_rows_become_valid_packages():
    rows = [
        {"Tracking ID": "TBA001", "Address": "411 W 36 St", "Bag ID": "BAG1"},
        {"Tracking ID": "TBA002", "Address": "409 W 36 St", "Bag ID": "BAG1"},
    ]
    result = APIManifestIngestor(rows).ingest()
    assert len(result.packages) == 2
    assert len(result.pending) == 0
    assert result.packages[0].tba == "TBA001"


def test_enriched_export_headers_all_go_pending():
    # An already-enriched export: no "Tracking ID" column (uses tba/block_key).
    # Every row lacks a readable Tracking ID → all pending, zero valid packages.
    rows = [
        {"tba": "TBA001", "normalised_address": "411 WEST 36 ST", "block_key": "W_36_St_400"},
        {"tba": "TBA002", "normalised_address": "409 WEST 36 ST", "block_key": "W_36_St_400"},
    ]
    result = APIManifestIngestor(rows).ingest()
    assert len(result.packages) == 0          # the guard's trigger condition
    assert len(result.pending) == 2


def test_blank_tracking_id_goes_pending():
    rows = [
        {"Tracking ID": "", "Address": "411 W 36 St"},
        {"Tracking ID": "   ", "Address": "409 W 36 St"},   # whitespace only
        {"Tracking ID": "TBA003", "Address": "415 W 36 St"},
    ]
    result = APIManifestIngestor(rows).ingest()
    assert len(result.packages) == 1
    assert len(result.pending) == 2


def test_tracking_id_is_case_sensitive_exact_match():
    # "tracking id" (lowercased) is NOT the expected header → pending.
    rows = [{"tracking id": "TBA001", "Address": "411 W 36 St"}]
    result = APIManifestIngestor(rows).ingest()
    assert len(result.packages) == 0
    assert len(result.pending) == 1
