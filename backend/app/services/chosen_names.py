"""Past records show a person's chosen name; the stored copy keeps the legal one (ADR-567 D3).

46 columns (`walker_name`, `resolved_by_name`, ...) hold a copy of a person's
name made when the row was written. The record keeps the legal name, the
owner's "name of record". What a reader sees is the person's CURRENT shown
name: when a registered row loads, its name field is replaced with
`set_committed_value`, which changes the loaded value without marking the row
dirty, so the swap can never be flushed back.

The columns come from employee_redaction.REGISTRY (Model, fk_attr, name_attr),
which a drift test already forces every new employee-name column into, so a
column added next month is swapped too without anyone remembering this file.

Chosen names are few, so the whole set is read once per Session, BEFORE the
first query that could load a registered row (do_orm_execute), never from
inside a load event: a query issued mid-load would race the outer result.
"""
from __future__ import annotations

import logging

from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

logger = logging.getLogger(__name__)

_CACHE_KEY = "adr567_chosen_names"
_LOADING_KEY = "adr567_loading"
_INSTALLED = False


def _chosen_names(session: Session) -> dict:
    return session.info.get(_CACHE_KEY) or {}


def forget(session: Session) -> None:
    """Call after a chosen name changes, so this session's next read sees it."""
    session.info.pop(_CACHE_KEY, None)


def _swap(target, name_attr: str, fk_attr: str) -> None:
    from sqlalchemy.orm import object_session
    session = object_session(target)
    if session is None:
        return
    emp_id = getattr(target, fk_attr, None)
    chosen = _chosen_names(session).get(emp_id) if emp_id is not None else None
    if chosen and getattr(target, name_attr, None) is not None:
        set_committed_value(target, name_attr, chosen[: _width(type(target), name_attr)])


def _width(model, attr: str) -> int:
    col = model.__table__.c.get(getattr(model, attr).property.columns[0].name)
    return getattr(col.type, "length", None) or 10_000


def install() -> None:
    """Attach the listeners once (idempotent)."""
    global _INSTALLED
    if _INSTALLED:
        return
    from app.models.employee import Employee
    from app.services.employee_redaction import REGISTRY

    registered = {}
    for model, fk_attr, name_attr in REGISTRY:
        if hasattr(model, fk_attr) and hasattr(model, name_attr):
            registered.setdefault(model, []).append((fk_attr, name_attr))

    registered_mappers = {m.__mapper__ for m in registered}

    @event.listens_for(Session, "do_orm_execute")
    def _load_chosen_names(state):
        session = state.session
        if not state.is_select or _CACHE_KEY in session.info or session.info.get(_LOADING_KEY):
            return
        # Only a select that can load a stored copy needs the names; most
        # requests never touch one and pay nothing.
        if not (set(state.all_mappers) & registered_mappers):
            return
        session.info[_LOADING_KEY] = True
        try:
            # In a SAVEPOINT: on Postgres a failed statement aborts the whole
            # transaction, and this lookup must never cost the request that
            # triggered it. On failure, stored copies show the stored (legal)
            # name, and the next session tries again.
            with session.begin_nested():
                rows = session.execute(
                    select(Employee.id, Employee.chosen_name).where(Employee.chosen_name.isnot(None))
                ).all()
            session.info[_CACHE_KEY] = {r[0]: r[1] for r in rows}
        except SQLAlchemyError as exc:
            logger.warning("chosen names: could not load; showing stored names: %s", type(exc).__name__)
            session.info[_CACHE_KEY] = {}
        finally:
            session.info.pop(_LOADING_KEY, None)

    for model, pairs in registered.items():
        def _on_load(target, context, _pairs=pairs):
            for fk_attr, name_attr in _pairs:
                _swap(target, name_attr, fk_attr)

        def _on_refresh(target, context, attrs, _pairs=pairs):
            for fk_attr, name_attr in _pairs:
                if attrs is None or name_attr in attrs or fk_attr in attrs:
                    _swap(target, name_attr, fk_attr)

        event.listen(model, "load", _on_load)
        event.listen(model, "refresh", _on_refresh)
    _INSTALLED = True
