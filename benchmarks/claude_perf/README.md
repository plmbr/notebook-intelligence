# Claude Code Performance Benchmark

Compare Claude Code response times between the terminal CLI and NBI's chat sidebar.

## Quick start

```bash
cd benchmarks/claude_perf

# Smoke test (terminal only, 2 iterations, one prompt)
python bench_runner.py --iterations 2 --prompts short --terminal-only

# Full terminal benchmark (25 iterations, all prompts)
python bench_runner.py --iterations 25 --terminal-only

# Full comparison (requires JupyterLab running on :8889 with Claude mode on)
python bench_runner.py --iterations 25

# Non-interleaved (all terminal first, then all NBI)
python bench_runner.py --iterations 25 --no-interleave

# View results
python report.py
```

## What it measures

| Metric            | Terminal                           | NBI Chat                                        |
| ----------------- | ---------------------------------- | ----------------------------------------------- |
| TTFT (ms)         | From Claude CLI's `result.ttft_ms` | From WebSocket send to first `nbiContent` chunk |
| Wall time (ms)    | subprocess spawn to exit           | WebSocket send to `stream-end`                  |
| CLI duration (ms) | `result.duration_ms`               | n/a                                             |
| API duration (ms) | `result.duration_api_ms`           | n/a                                             |
| Output tokens     | From `result.usage`                | n/a                                             |
| Output chars      | From `result.result` text length   | From streamed markdown chunks                   |

## Methodology notes

This benchmark measures **end-to-end user-perceived latency** for each surface, not isolated NBI overhead. Several structural asymmetries should be kept in mind when interpreting results:

**Different process models.** The terminal path spawns a fresh `claude -p` subprocess per run (pays Node.js startup, config loading, MCP server discovery each time). The NBI path hits an already-running JupyterLab server where the Agent SDK client is warm. This means the terminal "cold" cost is higher than NBI's, but for a different reason than NBI overhead.

**Different system prompts.** The `claude -p` CLI loads `~/.claude/CLAUDE.md`, project CLAUDE.md, skills, and MCP tool schemas into its system prompt. NBI builds a shorter JupyterLab-specific prompt. Different input token counts affect TTFT via prompt-cache behavior: each path warms its own cache key, and the first run in each block pays `cache_creation_input_tokens` cost.

**Prompt cache confound.** Run 0 ("cold") in each path is tagged separately and excluded from the comparison table's warm-only medians. The comparison table reflects steady-state performance after caches are populated.

**API latency dominates.** Claude API TTFT commonly spans 800-3000ms depending on load and cache state. NBI's local overhead (WebSocket parsing, thread dispatch, Agent SDK query: ~200-500ms) is a fraction of one standard deviation of API latency. With 25 samples, detecting a real 300ms difference on top of 2-5s API calls requires looking at the interleaved paired medians, not individual run comparisons.

**Interleaving.** By default, terminal and NBI runs are interleaved (terminal-NBI-terminal-NBI) to cancel out API load drift over the run. Use `--no-interleave` for block-sequential if needed.

## Prerequisites

- `claude` CLI on PATH (Claude Code 2.x)
- For NBI benchmarks: JupyterLab running with NBI installed, Claude mode enabled, no auth token (or pass `--nbi-token`)
- `pip install websockets` (for the WebSocket benchmark)

## Files

- `bench_terminal.py` - runs one prompt through `claude -p --output-format stream-json --verbose`
- `bench_nbi_ws.py` - connects to NBI's WebSocket and sends one chat request
- `bench_runner.py` - orchestrator (iterations, prompt bank, cold/warm, interleaving, summary table)
- `report.py` - reads `results.json` and prints formatted comparison with histograms
- `prompts.py` - the prompt bank (short / medium / code / long)
- `stats.py` - shared `summarize()` helper
