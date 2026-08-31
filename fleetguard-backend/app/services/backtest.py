"""Rule back-testing (spec section 6.4).

Replays a candidate rule over the trailing twelve months and reports what it
would actually have done:

  * precision   - of the alerts raised, the share followed by a real failure
  * coverage    - of the real failures, the share the rule caught
  * days_to_alert - median warning time before those failures

Consecutive alerts collapse into a single alert episode. Without that, a rule
that flags the same truck every week for two months scores sixty separate
"correct" alerts off one failure, and precision becomes a number that flatters
the product instead of describing it.

An episode is an *interval*, not a point: it opens at the first alert and
closes at the last alert of an unbroken run, where a gap longer than 45 days
is what breaks the run. That distinction matters. Treating an episode as its
start date alone either double-counts a long warning as several alerts
(destroying precision) or pushes the only matchable date months before the
failure (destroying coverage).

**Right-censoring.** An episode is judged by whether a failure follows it
inside the 90-day horizon. For an episode that ends within 90 days of the last
week of data, that horizon runs off the end of the observation window: the
failure it predicts may be perfectly real and simply not have happened yet.
Counting those as false positives measures where the data stops, not how good
the rule is - and it is a large effect here, because components at end of life
are exactly the ones still alerting when the data runs out. Such episodes are
therefore **excluded from precision entirely**, neither correct nor incorrect,
which is the standard treatment of a censored observation.

An episode that is already resolved is never censored: if the failure arrived,
the outcome was observed and the episode counts, however close to the window
edge it sits. Coverage needs no equivalent adjustment, because a failure that
happened is observed by definition.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from app.constants import (
    BACKTEST_EPISODE_DAYS,
    BACKTEST_LOOKBACK_DAYS,
    LABEL_HORIZON_DAYS,
    RED_THRESHOLD,
)
from app.services.scoring import probability_frame


@dataclass(frozen=True)
class BacktestResult:
    precision: float
    coverage: float
    days_to_alert: float
    sample_failures: int
    alert_episodes: int
    true_positive_episodes: int
    caught_failures: int
    alert_threshold: float
    censored_episodes: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


EMPTY_RESULT = BacktestResult(
    precision=0.0,
    coverage=0.0,
    days_to_alert=0.0,
    sample_failures=0,
    alert_episodes=0,
    true_positive_episodes=0,
    caught_failures=0,
    alert_threshold=RED_THRESHOLD,
    censored_episodes=0,
)


def collapse_to_episodes(
    dates: list[pd.Timestamp],
    episode_days: int,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Group alert dates into (first_alert, last_alert) runs.

    The gap is measured between successive alerts: a component that stays
    above the threshold week after week is one continuous warning nobody
    acted on, not a fresh warning every 45 days.
    """
    episodes: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    start: pd.Timestamp | None = None
    previous: pd.Timestamp | None = None

    for moment in sorted(dates):
        if previous is None:
            start = moment
        elif (moment - previous).days > episode_days:
            episodes.append((start, previous))
            start = moment
        previous = moment

    if start is not None and previous is not None:
        episodes.append((start, previous))
    return episodes


def backtest_rule(
    features: pd.DataFrame,
    failures: pd.DataFrame,
    weights: dict[str, float],
    alert_threshold: float = RED_THRESHOLD,
    lookback_days: int = BACKTEST_LOOKBACK_DAYS,
    horizon_days: int = LABEL_HORIZON_DAYS,
    episode_days: int = BACKTEST_EPISODE_DAYS,
) -> BacktestResult:
    """Replay one component's rule. `features` and `failures` are pre-filtered
    to that component by the caller."""
    if features.empty or not weights:
        return EMPTY_RESULT

    window_end = features["week_start_date"].max()
    window_start = window_end - pd.Timedelta(days=lookback_days)
    window = features[features["week_start_date"] >= window_start]
    if window.empty:
        return EMPTY_RESULT

    score = probability_frame(window, weights)
    alerts = window.loc[score >= alert_threshold, ["vin", "week_start_date"]]

    failures_in_window = failures[
        (failures["event_date"] >= window_start) & (failures["event_date"] <= window_end)
    ]

    failures_by_vin: dict[str, list[pd.Timestamp]] = {
        vin: sorted(group["event_date"].tolist())
        for vin, group in failures_in_window.groupby("vin", sort=False)
    }
    alerts_by_vin: dict[str, list[pd.Timestamp]] = {
        vin: sorted(group["week_start_date"].tolist())
        for vin, group in alerts.groupby("vin", sort=False)
    }

    horizon = pd.Timedelta(days=horizon_days)

    # Precision: an episode is correct if a failure lands during the warning
    # or inside the horizon after it stopped. An unresolved episode whose
    # horizon runs past the end of the data is censored, not counted wrong.
    total_episodes = 0
    true_positive_episodes = 0
    censored_episodes = 0
    for vin, alert_dates in alerts_by_vin.items():
        vin_failures = failures_by_vin.get(vin, [])
        for start, end in collapse_to_episodes(alert_dates, episode_days):
            if any(start <= failure <= end + horizon for failure in vin_failures):
                total_episodes += 1
                true_positive_episodes += 1
            elif end + horizon > window_end:
                censored_episodes += 1
            else:
                total_episodes += 1

    # Coverage: a failure is caught if any alert was raised inside the horizon
    # before it. Episode grouping is irrelevant here - the operator either got
    # a warning in time or did not.
    total_failures = 0
    caught_failures = 0
    lead_times: list[float] = []
    for vin, vin_failures in failures_by_vin.items():
        alert_dates = alerts_by_vin.get(vin, [])
        for failure in vin_failures:
            total_failures += 1
            warnings = [a for a in alert_dates if failure - horizon <= a <= failure]
            if warnings:
                caught_failures += 1
                lead_times.append((failure - min(warnings)).days)

    precision = true_positive_episodes / total_episodes if total_episodes else 0.0
    coverage = caught_failures / total_failures if total_failures else 0.0
    median_lead = float(pd.Series(lead_times).median()) if lead_times else 0.0

    return BacktestResult(
        precision=round(precision, 4),
        coverage=round(coverage, 4),
        days_to_alert=round(median_lead, 1),
        sample_failures=total_failures,
        alert_episodes=total_episodes,
        true_positive_episodes=true_positive_episodes,
        caught_failures=caught_failures,
        alert_threshold=alert_threshold,
        censored_episodes=censored_episodes,
    )
