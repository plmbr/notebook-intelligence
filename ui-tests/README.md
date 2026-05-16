# UI tests

Galata-based Playwright tests that drive a real JupyterLab instance with the
notebook-intelligence labextension installed.

## Run intent: manual, developer-triggered

This suite is intentionally **not** wired into the GitHub Actions `build.yml`
workflow. Each run boots a full JupyterLab process, real browser contexts,
and is comparatively expensive. We keep it as a high-signal pre-merge check
that the maintainer reaches for when:

- a PR touches a flow with a regression history (see the per-spec comments),
- you're refactoring the chat sidebar, the notebook generation toolbar, the
  cell-output toolbar, or the launcher,
- you want to lock down a bug fix before merging.

The jest unit suite (`jlpm jest` at the repo root) stays the default
on-every-commit check. Treat this Galata suite as top-of-the-pyramid coverage.

## What's covered

| Spec                       | Flows                                                                                                                                                                           |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extension.spec.ts`        | Smoke: extension activates, chat sidebar opens.                                                                                                                                 |
| `chat-sidebar.spec.ts`     | Footer icons + labels, gear-icon title, prefix popover via typed `/`, slash-button toggle, workspace file picker open + close, **regression #262** (Escape from picker search). |
| `notebook-toolbar.spec.ts` | Toolbar button renders, popover structure, **regression #231** (textarea focus on open), submit gating, Escape + outside-click dismissal.                                       |
| `cell-output.spec.ts`      | Hover toolbar renders Explain + Ask on clean cells, Troubleshoot only on errored cells, click activates the hovered cell.                                                       |
| `launcher.spec.ts`         | **Regression #260/#268** (Coding Agent tiles must add / dispose dynamically on capability change, not rely on `isVisible`).                                                     |

When a flow needs a real LLM round trip to pass we skip it rather than mock
the network — these tests are about UI state, not model output. Tests that
require a configured chat provider skip cleanly on a fresh Galata workspace.

## Running locally

From the repository root:

```bash
# Install the extension into the dev environment first.
pip install -e .[test]
jlpm
jlpm build

# Install ui-tests dependencies and Playwright browsers.
cd ui-tests
jlpm
jlpm playwright install chromium

# Run the suite.
jlpm test
```

`jlpm test:debug` opens the Playwright inspector for stepwise debugging;
`jlpm test:update` regenerates snapshots when an intentional UI change makes
the existing reference image stale.

## Layout

- `playwright.config.ts` — boots `jupyter lab` via `webServer`, points
  Playwright at `http://localhost:8888/lab`, enables traces + videos on
  failure, and retries twice on CI.
- `jupyter_server_test_config.py` — disables auth/XSRF and pins the port so
  Playwright connects deterministically.
- `tests/` — `*.spec.ts` files. Galata's `test`/`expect` come from
  `@jupyterlab/galata` and provide a `page` fixture that's already inside the
  lab shell.

## Adding tests

Each spec file is independent. Use Galata's [helpers](https://github.com/jupyterlab/jupyterlab/tree/main/galata)
(notebook commands, file browser, settings) before reaching for raw
`page.locator` so tests stay resilient to lab-side DOM changes.
