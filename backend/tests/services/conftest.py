"""
Skip collection of tests whose proprietary service modules are not present.

These services are excluded from the public repo (.gitignore). Tests run
locally where the files exist; CI skips them cleanly rather than erroring.
"""

import importlib
import os

collect_ignore = []

_PROPRIETARY = [
    ("test_assign_trainees.py", "app.services.assign_trainees"),
    ("test_assign_trainers.py", "app.services.assign_trainers"),
    ("test_assign_walkers.py", "app.services.assign_walkers"),
    ("test_calculate_weights.py", "app.services.calculate_weights"),
    ("test_run_dispatch.py", "app.services.run_dispatch"),
]

for _test_file, _module in _PROPRIETARY:
    try:
        importlib.import_module(_module)
    except ModuleNotFoundError:
        collect_ignore.append(os.path.join(os.path.dirname(__file__), _test_file))
