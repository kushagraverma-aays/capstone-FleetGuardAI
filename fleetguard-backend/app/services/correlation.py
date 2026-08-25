from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import pointbiserialr
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.config import SIGNAL_LABELS, SIGNALS


def correlate_part(features: pd.DataFrame, part_code: str) -> list[dict]:
    df = features[features["part_code"] == part_code]
    if df.empty or df["label_failed_30d"].nunique() < 2:
        return [
            {
                "signal": s,
                "label": SIGNAL_LABELS[s],
                "correlation": 0.0,
                "correlation_pct": 0.0,
                "p_value": 1.0,
                "lr_coefficient": 0.0,
                "significant": False,
            }
            for s in SIGNALS
        ]

    y = df["label_failed_30d"].to_numpy()
    X = df[SIGNALS].to_numpy()

    try:
        Xs = StandardScaler().fit_transform(X)
        lr = LogisticRegression(max_iter=1000, class_weight="balanced")
        lr.fit(Xs, y)
        lr_coefs = dict(zip(SIGNALS, lr.coef_[0]))
    except Exception:
        lr_coefs = dict.fromkeys(SIGNALS, 0.0)

    results = []
    for sig in SIGNALS:
        x = df[sig].to_numpy()
        if np.std(x) == 0:
            r, p = 0.0, 1.0
        else:
            r, p = pointbiserialr(y, x)
            if np.isnan(r):
                r, p = 0.0, 1.0
        r_pos = max(float(r), 0.0)
        results.append(
            {
                "signal": sig,
                "label": SIGNAL_LABELS[sig],
                "correlation": round(r_pos, 4),
                "correlation_pct": round(r_pos * 100, 1),
                "p_value": round(float(p), 6),
                "lr_coefficient": round(float(lr_coefs.get(sig, 0.0)), 4),
                "significant": bool(p < 0.05 and r_pos > 0),
            }
        )

    results.sort(key=lambda d: d["correlation"], reverse=True)
    return results


def fleet_precursors(features: pd.DataFrame, top_n: int = 6) -> list[dict]:
    if features.empty:
        return []

    counts = []
    for sig in SIGNALS:
        cutoff = features[sig].quantile(0.75)
        hits = int(((features[sig] >= cutoff) & (features["label_failed_30d"] == 1)).sum())
        counts.append({"signal": sig, "label": SIGNAL_LABELS[sig], "count": hits})

    counts.sort(key=lambda d: d["count"], reverse=True)
    return counts[:top_n]