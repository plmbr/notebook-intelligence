"""Shared statistics helpers for the benchmark suite."""

import math
import statistics as _stats


def summarize(results: list[dict], metric: str, *, tag_filter: str | None = None) -> dict | None:
    """Compute summary statistics for a single metric across a results list.

    When `tag_filter` is set (e.g., "warm"), only results with a matching
    `tag` field are included. Results with an `error` key or a None/missing
    value for `metric` are always excluded.
    """
    values = [
        r[metric]
        for r in results
        if metric in r
        and r[metric] is not None
        and "error" not in r
        and (tag_filter is None or r.get("tag") == tag_filter)
    ]
    if not values:
        return None
    n = len(values)
    s = sorted(values)
    return {
        "n": n,
        "mean": round(_stats.mean(values), 1),
        "median": round(_stats.median(values), 1),
        "stdev": round(_stats.stdev(values), 1) if n > 1 else 0,
        "p95": round(s[math.ceil(n * 0.95) - 1], 1) if n >= 5 else None,
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }
