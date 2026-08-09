"""segment_map — persistent LION topology write-through cache (ADR-236).

Covers the pure logic: connector-pair generation (which must only pair bounds of
the same kind), street parsing, blockface response handling, and adjacency
chaining. DB upsert idempotency is exercised against a real session in the
integration check noted in the ADR; here we keep to unit-testable surface.
"""
from unittest.mock import MagicMock, patch

try:
    from app.services.segment_map import fetch_blockface, load_adjacency
    # enrich_manifest transitively imports derive_block_key, which is also
    # gitignored — so both imports belong inside the same guard. Guarding only the
    # first left the second as a collection error, which aborts the whole run.
    from app.tasks.enrich_manifest import _street_of, _street_sort_key
except (ImportError, ModuleNotFoundError):
    import pytest
    pytest.skip("proprietary sort deps not available (CI skip)", allow_module_level=True)


# ---------------------------------------------------------------------------
# _street_of — /blockface.json needs a STREET, not a full address
# ---------------------------------------------------------------------------

class TestStreetOf:
    def test_strips_house_number(self):
        assert _street_of("168 WEST 23 STREET") == "WEST 23 STREET"

    def test_strips_house_number_on_avenue(self):
        assert _street_of("501 10 AVENUE") == "10 AVENUE"

    def test_no_house_number_returns_none(self):
        # Not a normalised address — not safe to pass to the API as a street.
        assert _street_of("WEST 23 STREET") is None

    def test_none_and_empty(self):
        assert _street_of(None) is None
        assert _street_of("") is None


# ---------------------------------------------------------------------------
# _street_sort_key — "consecutive" must mean geographically adjacent
# ---------------------------------------------------------------------------

class TestStreetSortKey:
    def test_numbered_streets_sort_numerically(self):
        streets = ["WEST 10 STREET", "WEST 9 STREET", "WEST 23 STREET"]
        assert sorted(streets, key=_street_sort_key) == [
            "WEST 9 STREET", "WEST 10 STREET", "WEST 23 STREET",
        ]
        # ...which alphabetical ordering would get wrong:
        assert sorted(streets) != sorted(streets, key=_street_sort_key)

    def test_unnumbered_sort_after_numbered(self):
        out = sorted(["BROADWAY", "WEST 42 STREET"], key=_street_sort_key)
        assert out == ["WEST 42 STREET", "BROADWAY"]


# ---------------------------------------------------------------------------
# fetch_blockface — response handling
# ---------------------------------------------------------------------------

def _resp(ok=True, payload=None, status=200):
    m = MagicMock()
    m.ok = ok
    m.status_code = status
    m.json.return_value = payload or {}
    return m


class TestFetchBlockface:
    def _key(self):
        return patch("app.services.segment_map.settings.geoclient_app_key", "k")

    def test_extracts_segment_and_nodes(self):
        payload = {"blockface": {
            "segmentIdentifier": "0033840", "fromNode": "0021354",
            "toNode": "0021355", "physicalId": "0001416"}}
        with self._key(), patch("app.services.segment_map.requests.get",
                                return_value=_resp(payload=payload)):
            got = fetch_blockface("9 AVENUE", "WEST 42 STREET", "WEST 43 STREET")
        assert got["segment_id"] == "0033840"
        assert got["from_lion_node_id"] == "0021354"
        assert got["to_lion_node_id"] == "0021355"
        assert got["source"] == "connector_walk"

    def test_http_200_without_segment_is_a_miss_not_an_error(self):
        # Observed on 9 Ave, W 40 -> W 41. The graph keeps the gap; block_key
        # adjacency covers it. Must NOT raise.
        with self._key(), patch("app.services.segment_map.requests.get",
                                return_value=_resp(payload={"blockface": {}})):
            assert fetch_blockface("9 AVENUE", "W 40 ST", "W 41 ST") is None

    def test_http_error_returns_none(self):
        with self._key(), patch("app.services.segment_map.requests.get",
                                return_value=_resp(ok=False, status=404)):
            assert fetch_blockface("X", "A", "B") is None

    def test_exception_is_swallowed(self):
        # Best-effort: GeoClient being down must never fail a sort.
        with self._key(), patch("app.services.segment_map.requests.get",
                                side_effect=RuntimeError("boom")):
            assert fetch_blockface("X", "A", "B") is None

    def test_no_api_key_short_circuits(self):
        with patch("app.services.segment_map.settings.geoclient_app_key", ""):
            assert fetch_blockface("X", "A", "B") is None


# ---------------------------------------------------------------------------
# load_adjacency — segments sharing a LION node are adjacent
# ---------------------------------------------------------------------------

class TestLoadAdjacency:
    def test_empty_input_returns_empty(self):
        assert load_adjacency(MagicMock(), []) == {}

    def test_segments_sharing_a_node_are_adjacent(self):
        # The real 9-AVENUE chain: consecutive connectors share a node, which is
        # what stitches separate street clusters into one graph.
        a = MagicMock(segment_id="0033838", from_lion_node_id="0021353", to_lion_node_id="0021354")
        b = MagicMock(segment_id="0033840", from_lion_node_id="0021354", to_lion_node_id="0021355")
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.side_effect = [[a], [a, b]]

        adj = load_adjacency(db, ["0033838"])
        assert adj["0033838"] == {"0033840"}
        assert adj["0033840"] == {"0033838"}


# ---------------------------------------------------------------------------
# load_node_adjacency — NODE-keyed graph for misroute detection (ADR-238 D4b)
# ---------------------------------------------------------------------------

class TestLoadNodeAdjacency:
    def test_empty_input_returns_empty(self):
        from app.services.segment_map import load_node_adjacency
        assert load_node_adjacency(MagicMock(), []) == {}

    def test_nodes_joined_by_a_segment_are_adjacent(self):
        # A segment IS an edge between its two nodes — that is the whole model.
        from app.services.segment_map import load_node_adjacency
        s = MagicMock(segment_id="0033840",
                      from_lion_node_id="0021354", to_lion_node_id="0021355")
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.side_effect = [[s], [s]]
        adj = load_node_adjacency(db, ["0033840"])
        assert adj["0021354"] == {"0021355"}
        assert adj["0021355"] == {"0021354"}

    def test_connector_bridges_two_clusters(self):
        # The connector carries no packages (never in segment_ids) but shares a
        # node with each side — this is what a per-sort reconstruction cannot see.
        from app.services.segment_map import load_node_adjacency
        left = MagicMock(segment_id="A", from_lion_node_id="n1", to_lion_node_id="n2")
        conn = MagicMock(segment_id="C", from_lion_node_id="n2", to_lion_node_id="n3")
        right = MagicMock(segment_id="B", from_lion_node_id="n3", to_lion_node_id="n4")
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.side_effect = [
            [left, right],            # seeds
            [left, conn, right],      # one hop out — pulls in the connector
        ]
        adj = load_node_adjacency(db, ["A", "B"])
        assert "n3" in adj["n2"], "connector must join the two clusters"

    def test_segment_with_one_node_is_skipped(self):
        # A dangling segment cannot form an edge; it must not crash or self-link.
        from app.services.segment_map import load_node_adjacency
        s = MagicMock(segment_id="X", from_lion_node_id="n1", to_lion_node_id=None)
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.side_effect = [[s], [s]]
        assert load_node_adjacency(db, ["X"]) == {}
