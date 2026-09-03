"""A small cache in front of the feature table.

Building the feature table for one component crosses 31,200 vehicle-weeks with
the job-card history and takes the better part of a second. Rule Studio calls
`POST /api/rules/preview` on **every signal toggle**, and spec section 9 asks
that moment to feel instant, so recomputing per keystroke is not an option.

The cache key is a cheap fingerprint of the underlying data - the latest
telematics week plus the job-card count - rather than a timer. That way a
re-seed invalidates the cache on its own, without anything having to remember
to call an invalidation hook from a separate process.
"""

from __future__ import annotations

import threading

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import JobCard, TelematicsWeekly
from app.services.features import build_feature_table
from app.services.rules_engine import load_failures

# Eight components at roughly 6 MB of frame each is a few tens of megabytes -
# acceptable for a single-process API, and the whole set is what Rule Studio
# and the overview screen actually touch.
_lock = threading.Lock()
_features: dict[tuple, pd.DataFrame] = {}
_failures: dict[tuple, pd.DataFrame] = {}


def data_fingerprint(session: Session) -> tuple:
    """Changes whenever the fleet is re-seeded or new events land."""
    latest_week = session.execute(
        select(func.max(TelematicsWeekly.week_start_date))
    ).scalar_one_or_none()
    job_cards = session.execute(
        select(func.count()).select_from(JobCard)
    ).scalar_one()
    return (str(latest_week), int(job_cards))


def features_for_part(session: Session, part_code: str) -> pd.DataFrame:
    """The feature table for one component, memoised against the fingerprint."""
    key = (*data_fingerprint(session), part_code)
    with _lock:
        cached = _features.get(key)
    if cached is not None:
        return cached

    frame = build_feature_table(session, [part_code])
    with _lock:
        # A new fingerprint means every older entry is stale; drop them rather
        # than letting a long-lived process accumulate dead fleets.
        stale = [k for k in _features if k[:2] != key[:2]]
        for k in stale:
            _features.pop(k, None)
        _features[key] = frame
    return frame


def failures_for_part(session: Session, part_code: str) -> pd.DataFrame:
    """Failure events for one component - the back-test's ground truth."""
    key = data_fingerprint(session)
    with _lock:
        cached = _failures.get(key)
    if cached is None:
        cached = load_failures(session)
        with _lock:
            _failures.clear()
            _failures[key] = cached
    if cached.empty:
        return cached
    return cached[cached["part_code"] == part_code]


def clear() -> None:
    """Drop everything. Used by tests and after a deliberate re-seed."""
    with _lock:
        _features.clear()
        _failures.clear()
