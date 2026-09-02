"""Signal recovery validation (spec section 5).

This script is the project's scientific credibility. The generator plants
hidden weights, generates failures from them, and then throws the weights away
as far as the rest of the system is concerned. Here we run the real correlation
engine over the resulting data and check that it rediscovers relationships it
was never told about.

Target: >= 90% top-N signal recovery. Exit code is non-zero below that, so the
check can gate a build.

Run:  python -m scripts.validate_recovery
"""

from __future__ import annotations

import argparse
import json
import sys

from scipy import stats
from sqlalchemy import select

from app.config import DATA_DIR
from app.db import SessionLocal
from app.models import Part
from app.services.correlation import rank_signals
from app.services.features import build_feature_table

TARGET_RECOVERY = 0.90


def load_planted_weights() -> dict[str, dict[str, float]]:
    path = DATA_DIR / "planted_weights.json"
    if not path.exists():
        raise SystemExit(
            f"No ground truth at {path}. Run 'python -m scripts.generate_data' first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def rank_agreement(planted: dict[str, float], recovered_order: list[str]) -> float:
    """Spearman correlation between planted weight order and recovered order.

    Recovering the right set of signals but in the wrong order is a weaker
    result than recovering the order too, so this is reported alongside.
    """
    signals = list(planted.keys())
    if len(signals) < 3:
        return float("nan")
    planted_rank = [sorted(signals, key=lambda s: -planted[s]).index(s) for s in signals]
    recovered_rank = [
        recovered_order.index(s) if s in recovered_order else len(recovered_order)
        for s in signals
    ]
    result = stats.spearmanr(planted_rank, recovered_rank)
    return float(result.statistic)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate planted signal recovery.")
    parser.add_argument(
        "--target",
        type=float,
        default=TARGET_RECOVERY,
        help="Recovery threshold to pass (default 0.90).",
    )
    args = parser.parse_args()

    planted_weights = load_planted_weights()

    session = SessionLocal()
    try:
        print("Building feature table...")
        features = build_feature_table(session)
        if features.empty:
            raise SystemExit("Feature table is empty. Has the data been generated?")

        part_names = dict(
            session.execute(select(Part.part_code, Part.part_name)).all()
        )
    finally:
        session.close()

    print(f"Feature rows: {len(features):,}")
    print(f"Positive labels: {int(features['failed_within_horizon'].sum()):,}")
    print()

    header = (
        f"{'Component':<20} {'N':>3} {'Recovered':>10} {'Hit':>7} "
        f"{'Rank rho':>9}  Missed"
    )
    print(header)
    print("-" * len(header))

    total_planted = 0
    total_recovered = 0
    rows: list[tuple[str, float]] = []

    for part_code, planted in planted_weights.items():
        subset = features[features["part_code"] == part_code]
        correlations = rank_signals(subset)
        recovered_order = [c.signal for c in correlations]

        n = len(planted)
        top_n = set(recovered_order[:n])
        planted_set = set(planted.keys())
        hits = planted_set & top_n
        missed = sorted(planted_set - top_n)

        total_planted += n
        total_recovered += len(hits)
        share = len(hits) / n
        rows.append((part_code, share))

        rho = rank_agreement(planted, recovered_order)
        name = part_names.get(part_code, part_code)
        print(
            f"{name:<20} {n:>3} {len(hits):>4}/{n:<5} {share:>6.0%} "
            f"{rho:>9.2f}  {', '.join(missed) if missed else '-'}"
        )

    overall = total_recovered / total_planted if total_planted else 0.0
    weakest = min(rows, key=lambda r: r[1]) if rows else ("-", 0.0)

    print("-" * len(header))
    print()
    print(f"SIGNAL RECOVERY: {overall:.1%}  ({total_recovered}/{total_planted} planted signals)")
    print(f"Weakest component: {part_names.get(weakest[0], weakest[0])} at {weakest[1]:.0%}")
    print(f"Target: {args.target:.0%}")
    print()

    if overall >= args.target:
        print("PASS - the engine rediscovers the planted relationships.")
        return 0

    print("FAIL - recovery is below target. Retune the generator before proceeding.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
