#!/usr/bin/env python3
"""Orchestrate the Claude Code performance benchmark.

Usage:
    python bench_runner.py                          # full run, 25 iterations
    python bench_runner.py --iterations 3           # quick sanity check
    python bench_runner.py --prompts short           # single prompt
    python bench_runner.py --terminal-only           # skip NBI
    python bench_runner.py --nbi-only                # skip terminal
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure sibling modules are importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompts import PROMPTS
from bench_terminal import run_once as terminal_run
from bench_nbi_ws import run_once as nbi_run
from stats import summarize


def collect(
    runner,
    prompt_text: str,
    iterations: int,
    *,
    label: str,
    cooldown: float,
    **kwargs,
) -> list[dict]:
    results = []
    for i in range(iterations):
        tag = "cold" if i == 0 else "warm"
        print(f"  [{label}] {tag} run {i+1}/{iterations}...", end=" ", flush=True)
        try:
            result = runner(prompt_text, **kwargs)
        except Exception as e:
            result = {
                "error": f"{type(e).__name__}: {str(e)[:200]}",
                "wall_ms": 0,
            }
        result["run_index"] = i
        result["tag"] = tag
        results.append(result)
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            ttft = result.get("ttft_ms")
            wall = result.get("wall_ms") or result.get("duration_ms")
            print(f"ttft={ttft}ms  wall={wall}ms")
        if i < iterations - 1:
            time.sleep(cooldown)
    return results


def print_comparison(terminal_results: list[dict], nbi_results: list[dict], prompt_id: str):
    print(f"\n{'='*70}")
    print(f"  Prompt: {prompt_id}  (warm runs only, cold shown separately)")
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
        t_summary = summarize(terminal_results, key, tag_filter="warm") if terminal_results else None
        n_summary = summarize(nbi_results, key, tag_filter="warm") if nbi_results else None

        t_val = f"{t_summary['median']:.0f}" if t_summary else "n/a"
        n_val = f"{n_summary['median']:.0f}" if n_summary else "n/a"

        if t_summary and n_summary:
            delta = n_summary["median"] - t_summary["median"]
            delta_pct = (delta / t_summary["median"] * 100) if t_summary["median"] else 0
            delta_str = f"{delta:+.0f}"
            pct_str = f"{delta_pct:+.1f}%"
        else:
            delta_str = "n/a"
            pct_str = ""

        print(f"{label:<22} {t_val:>12} {n_val:>12} {delta_str:>12} {pct_str:>10}")

    # Cold vs warm breakdown for TTFT
    for label, results in [("Terminal", terminal_results), ("NBI Chat", nbi_results)]:
        if not results:
            continue
        cold = [r for r in results if r.get("tag") == "cold" and "error" not in r]
        warm_summary = summarize(results, "ttft_ms", tag_filter="warm")
        cold_ttft = cold[0].get("ttft_ms") if cold else None
        print(f"\n  {label} TTFT breakdown:")
        print(f"    Cold start: {cold_ttft}ms" if cold_ttft else "    Cold start: n/a")
        if warm_summary:
            print(f"    Warm (median of {warm_summary['n']}): {warm_summary['median']}ms  "
                  f"(p95: {warm_summary.get('p95', 'n/a')}ms, stdev: {warm_summary['stdev']}ms)")


def main():
    parser = argparse.ArgumentParser(description="Claude Code performance benchmark")
    parser.add_argument("--iterations", "-n", type=int, default=25)
    parser.add_argument("--prompts", "-p", nargs="*", default=list(PROMPTS.keys()),
                        choices=list(PROMPTS.keys()))
    parser.add_argument("--terminal-only", action="store_true")
    parser.add_argument("--nbi-only", action="store_true")
    parser.add_argument("--interleave", action="store_true", default=True,
                        help="interleave terminal/NBI runs (default; reduces API drift bias)")
    parser.add_argument("--no-interleave", dest="interleave", action="store_false",
                        help="run all terminal first, then all NBI")
    parser.add_argument("--nbi-host", default="localhost")
    parser.add_argument("--nbi-port", type=int, default=8889)
    parser.add_argument("--nbi-token", default="")
    parser.add_argument("--cooldown", type=float, default=2.0,
                        help="seconds between runs to avoid rate limits")
    parser.add_argument("--output", "-o", type=str, default=str(
        Path(__file__).resolve().parent / "results.json"))
    args = parser.parse_args()

    run_terminal = not args.nbi_only
    run_nbi = not args.terminal_only
    interleave = args.interleave and run_terminal and run_nbi

    all_results = {
        "meta": {
            "iterations": args.iterations,
            "prompts": args.prompts,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_terminal": run_terminal,
            "run_nbi": run_nbi,
            "interleaved": interleave,
        },
        "results": {},
    }

    for prompt_id in args.prompts:
        prompt_text = PROMPTS[prompt_id]["text"]
        print(f"\n{'#'*70}")
        print(f"# Prompt: {prompt_id} ({PROMPTS[prompt_id]['description']})")
        print(f"# \"{prompt_text[:60]}{'...' if len(prompt_text) > 60 else ''}\"")
        print(f"# Iterations: {args.iterations}  Interleaved: {interleave}")
        print(f"{'#'*70}")

        terminal_results: list[dict] = []
        nbi_results: list[dict] = []

        if interleave:
            print(f"\n  --- Interleaved (terminal then NBI per iteration) ---")
            for i in range(args.iterations):
                tag = "cold" if i == 0 else "warm"

                print(f"  [terminal] {tag} run {i+1}/{args.iterations}...", end=" ", flush=True)
                try:
                    t_result = terminal_run(prompt_text)
                except Exception as e:
                    t_result = {"error": f"{type(e).__name__}: {str(e)[:200]}", "wall_ms": 0}
                t_result["run_index"] = i
                t_result["tag"] = tag
                terminal_results.append(t_result)
                if "error" in t_result:
                    print(f"ERROR: {t_result['error']}")
                else:
                    print(f"ttft={t_result.get('ttft_ms')}ms  wall={t_result.get('wall_ms')}ms")

                time.sleep(args.cooldown)

                print(f"  [nbi]      {tag} run {i+1}/{args.iterations}...", end=" ", flush=True)
                try:
                    n_result = nbi_run(
                        prompt_text,
                        host=args.nbi_host, port=args.nbi_port, token=args.nbi_token,
                    )
                except Exception as e:
                    n_result = {"error": f"{type(e).__name__}: {str(e)[:200]}", "wall_ms": 0}
                n_result["run_index"] = i
                n_result["tag"] = tag
                nbi_results.append(n_result)
                if "error" in n_result:
                    print(f"ERROR: {n_result['error']}")
                else:
                    print(f"ttft={n_result.get('ttft_ms')}ms  wall={n_result.get('wall_ms')}ms")

                if i < args.iterations - 1:
                    time.sleep(args.cooldown)
        else:
            if run_terminal:
                print(f"\n  --- Terminal CLI ---")
                terminal_results = collect(
                    terminal_run, prompt_text, args.iterations,
                    label="terminal", cooldown=args.cooldown,
                )

            if run_nbi:
                print(f"\n  --- NBI Chat (WebSocket) ---")
                nbi_results = collect(
                    nbi_run, prompt_text, args.iterations,
                    label="nbi", cooldown=args.cooldown,
                    host=args.nbi_host, port=args.nbi_port, token=args.nbi_token,
                )

        all_results["results"][prompt_id] = {
            "terminal": terminal_results,
            "nbi": nbi_results,
        }

        print_comparison(terminal_results, nbi_results, prompt_id)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
