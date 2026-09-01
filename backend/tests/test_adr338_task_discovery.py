"""Every scheduled task actually exists and is registered (ADR-338).

`celery_app` used a hand-maintained `include=[...]` list of 17 module paths. A
beat entry naming a module nobody imported fails with NO error: the schedule
fires, Celery has no task registered under that name, and the work never
happens. ADR-337's health check hit exactly that, and it was caught only because
someone went looking at how registration works.

These tests close the gap that discovery alone does not: discovery fixes a
MISSING MODULE, but a typo in a beat entry's task name is still silent.
"""
import importlib
import os
import pkgutil

from app.celery_app import celery_app


def test_discovery_finds_every_module_on_disk():
    """The whole point of replacing the hand-maintained list."""
    import app.tasks

    on_disk = {
        f"app.tasks.{m.name}" for m in pkgutil.iter_modules(app.tasks.__path__)
    }
    assert set(celery_app.conf.include) == on_disk, (
        "discovery and the filesystem disagree — a task module is invisible"
    )


def test_discovery_is_not_a_hand_maintained_list():
    """A literal list drifts the moment someone adds a module and forgets."""
    import ast

    src = open(
        os.path.join(os.path.dirname(__file__), "..", "app", "celery_app.py")
    ).read()

    # Asserted on the `include=` KEYWORD, not on the text. A substring check for
    # '"app.tasks.' matched the f-string INSIDE _task_modules() — which is the
    # discovery mechanism itself, not a hardcoded list.
    tree = ast.parse(src)
    include_args = [
        ast.unparse(kw.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "include"
    ]
    assert include_args, "Celery() is constructed without an include argument"
    for arg in include_args:
        assert "_task_modules()" in arg, (
            f"include is a literal list rather than discovery: {arg[:90]}"
        )


def test_every_scheduled_task_is_actually_registered():
    """THE check that would have caught the ADR-337 gap.

    Discovery cannot catch a TYPO: a beat entry whose `task` string does not
    match any `@celery_app.task(name=...)` still fires into nothing. This
    compares the two sets directly.
    """
    for module in celery_app.conf.include:
        importlib.import_module(module)

    scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    registered = set(celery_app.tasks.keys())

    missing = scheduled - registered
    assert not missing, (
        f"scheduled but not registered — these fire into nothing: {sorted(missing)}"
    )


def test_the_schedule_is_not_empty():
    """Guards the test above from passing vacuously if the schedule is lost."""
    assert len(celery_app.conf.beat_schedule) >= 20
