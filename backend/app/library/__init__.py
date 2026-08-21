"""Building Library client boundary (ADR-237 D1).

AsheFlow reaches building intelligence ONLY through `app.library.client`, and
street topology ONLY through `services/segment_map.py`. Importing
`BuildingProfileLibrary` or `StreetSegment` anywhere else re-couples the two
products; asserted by tests/services/test_library_boundary.py.
"""
