/**
 * Galata is JupyterLab's Playwright wrapper. It boots a JupyterLab server with
 * a known port + auth token, mounts a workspace inside ``ui-tests/``, and
 * exposes a ``page`` fixture that already knows how to drive the lab UI.
 * See https://github.com/jupyterlab/jupyterlab/tree/main/galata
 */
// Galata re-exports Playwright's test/expect but ships no `defineConfig` of
// its own; import the config helper from `@playwright/test` directly.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  // Tests live next to this config so they can ``import { test, expect } from
  // '@jupyterlab/galata'`` without long relative paths.
  testDir: './tests',

  // Lab takes a while to boot the first time; allow a generous timeout per
  // test before failing. Local runs feel fast; CI runs are the bottleneck.
  timeout: 90_000,

  // Galata's ``webServer`` config starts ``jupyter lab`` for us. The actual
  // port + token are wired up in jupyter_server_test_config.py.
  webServer: {
    command: 'jlpm start',
    url: 'http://localhost:8888/lab',
    timeout: 120_000,
    reuseExistingServer: !process.env.CI
  },

  use: {
    // Galata's `page` fixture goes directly to the lab shell; baseURL is the
    // server root.
    baseURL: 'http://localhost:8888',
    // ``trace: on-first-retry`` strikes the right balance for CI — the first
    // pass is fast, but failures keep enough context to diagnose flakes.
    trace: 'on-first-retry',
    video: 'retain-on-failure'
  },

  // Lock to chromium — the README only documents installing chromium and the
  // smoke suite has no per-browser concerns. Without an explicit ``projects``
  // declaration Playwright would run on every installed browser, which costs
  // CI time and risks confusing failures from a half-installed firefox or
  // webkit.
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ],

  // Two retries on CI absorb the occasional transient flake (kernel
  // start-up, websocket warm-up) without hiding real regressions.
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list'
});
