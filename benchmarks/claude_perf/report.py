#!/usr/bin/env python3
"""Read benchmark results and print a formatted report.

Usage:
    python report.py                                        # default results.json
    python report.py benchmarks/claude_perf/results.json    # explicit path
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stats import summarize


def ascii_histogram(values: list[float], *, width: int = 40, bins: int = 10) -> list[str]:
    if not values:
        return ["  (no data)"]
    lo, hi = min(values), max(values)
    if lo == hi:
        return [f"  all values = {lo:.0f}ms"]
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / step), bins - 1)
        counts[idx] += 1
    max_count = max(counts)
    lines = []
    for i, count in enumerate(counts):
        bar_len = int(count / max_count * width) if max_count else 0
        edge = lo + i * step
        lines.append(f"  {edge:7.0f}ms |{'#' * bar_len} ({count})")
    return lines


def print_report(data: dict):
    meta = data.get("meta", {})
    print(f"Benchmark run: {meta.get('timestamp', 'unknown')}")
    print(f"Iterations: {meta.get('iterations', '?')}")
    print(f"Interleaved: {meta.get('interleaved', 'unknown')}")
    print(f"Prompts: {', '.join(meta.get('prompts', []))}")
    print()

    for prompt_id, prompt_data in data.get("results", {}).items():
        terminal = prompt_data.get("terminal", [])
        nbi = prompt_data.get("nbi", [])

        print(f"{'='*70}")
        print(f"  {prompt_id}  (warm runs only)")
        print(f"{'='*70}")

        metrics = [
            ("ttft_ms", "TTFT (ms)"),
            ("wall_ms", "Wall time (ms)"),
            ("duration_ms", "CLI duration (ms)"),
            ("duration_api_ms", "API duration (ms)"),
            ("output_tokens", "Output tokens"),
            ("output_chars", "Output chars"),
        ]

        header = f"{'Metric':<22} {'Terminal':>12} {'NBI Chat':>12} {'Delta':>12} {'Delta %':>10}"
        print(header)
        print("-" * 70)

        for key, label in metrics:
            t = summarize(terminal, key, tag_filter="warm")
            n = summarize(nbi, key, tag_filter="warm")
            t_val = f"{t['median']:.0f}" if t else "n/a"
            n_val = f"{n['median']:.0f}" if n else "n/a"
            if t and n:
                delta = n["median"] - t["median"]
                pct = (delta / t["median"] * 100) if t["median"] else 0
                print(f"{label:<22} {t_val:>12} {n_val:>12} {delta:>+12.0f} {pct:>+9.1f}%")
            else:
                print(f"{label:<22} {t_val:>12} {n_val:>12} {'n/a':>12} {'':>10}")

        # TTFT histograms (warm only)
        for label, results in [("Terminal", terminal), ("NBI Chat", nbi)]:
            if not results:
                continue
            warm = [
                r["ttft_ms"]
                for r in results
                if r.get("tag") == "warm"
                and "ttft_ms" in r
                and r["ttft_ms"] is not None
                and "error" not in r
            ]
            if warm:
                print(f"\n  {label} warm TTFT distribution:")
                for line in ascii_histogram(warm):
                    print(line)

        # Cold breakdown
        for label, results in [("Terminal", terminal), ("NBI Chat", nbi)]:
            if not results:
                continue
            cold = [r for r in results if r.get("tag") == "cold" and "error" not in r]
            cold_ttft = cold[0].get("ttft_ms") if cold else None
            if cold_ttft:
                print(f"\n  {label} cold-start TTFT: {cold_ttft}ms")

        # Error summary
        for label, results in [("Terminal", terminal), ("NBI Chat", nbi)]:
            errors = [r for r in results if "error" in r]
            if errors:
                print(f"\n  {label} errors: {len(errors)}/{len(results)}")
                for e in errors[:3]:
                    print(f"    - {e['error'][:80]}")

        print()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(__file__).resolve().parent / "results.json")
    data = json.loads(Path(path).read_text())
    print_report(data)


if __name__ == "__main__":
    main()
