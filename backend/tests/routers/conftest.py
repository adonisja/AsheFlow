"""
Skip collection of router tests whose proprietary modules are not present.

app.routers.walker_routes lives in AsheFlow-private and is injected onto the
EC2 at deploy time — it is never present on the CI runner. Tests run fully
locally where the file exists; CI skips them cleanly rather than erroring.
"""
import importlib
import os

collect_ignore = []

_PROPRIETARY = [
    ("test_persist_routes.py", "app.routers.walker_routes"),
]

for _test_file, _module in _PROPRIETARY:
    try:
        importlib.import_module(_module)
    except ModuleNotFoundError:
        collect_ignore.append(os.path.join(os.path.dirname(__file__), _test_file))
