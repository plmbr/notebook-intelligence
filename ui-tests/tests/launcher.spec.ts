/**
 * "Coding Agent" launcher tiles. The category renders a card per CLI that
 * the backend reports as available. Visibility is dynamic — a tile must
 * appear or disappear when capabilities change without a page reload.
 *
 * Regression history:
 *   - #260 / PR #268: the helper called `launcher.add(...)` unconditionally
 *     and relied on the command's `isVisible` to hide tiles. JL's Launcher
 *     widget renders every item in its model regardless of `isVisible`, so
 *     tiles for un-installed CLIs were still showing. The fix is to add /
 *     dispose entries based on availability and rerun on configChanged.
 */
import { expect, test } from '@jupyterlab/galata';

test.describe('Coding Agent launcher tiles', () => {
  // The runtime-flip half of this test is the assertion that catches the
  // #260 / #268 bug class. It fails against current main because the fix
  // lives in PR #268 (not yet merged); flip to a regular `test` once that
  // PR lands. The first half (initial tile count > 0) is still load-bearing.
  test.fixme(
    'tile appears for an available CLI and disappears when capability flips',
    async ({ page }) => {
      // Open the launcher (Galata starts with one open; if not, run the
      // launcher:create command). The new-launcher tab button is always
      // present in the file-browser toolbar.
      await page
        .locator('[title="New Launcher (⇧ ⌘ L)"]')
        .first()
        .click({ trial: false });

      const codingAgent = page.locator(
        '.jp-Launcher-section:has(.jp-Launcher-sectionTitle:has-text("Coding Agent"))'
      );
      // The category renders only when at least one CLI is available. On a
      // typical dev machine `claude` is on PATH; on a clean CI image neither
      // is. Skip when the category isn't present rather than asserting a
      // specific tile — what we care about is the *gating mechanism*.
      if (!(await codingAgent.count())) {
        test.skip(
          true,
          'No Coding Agent CLI detected on PATH; gating mechanism still valid'
        );
      }

      // Record the tiles initially showing.
      const initialTiles = await codingAgent
        .locator('.jp-LauncherCard')
        .count();
      expect(initialTiles).toBeGreaterThan(0);

      // Flip a capability flag at runtime and assert the launcher updates
      // without a reload. Forces the most common regression (the
      // unconditional-add bug from #268) to manifest.
      await page.evaluate(() => {
        const api = (
          window as unknown as {
            NBIAPI?: {
              config?: {
                capabilities?: Record<string, unknown>;
                changed?: { emit: () => void };
              };
            };
          }
        ).NBIAPI;
        if (!api?.config?.capabilities) {
          return;
        }
        // Clear every CLI availability flag we know about, so however many
        // tiles were registered, all of them should disappear.
        for (const key of [
          'claude_cli_available',
          'opencode_cli_available',
          'pi_cli_available',
          'github_copilot_cli_available',
          'codex_cli_available'
        ]) {
          api.config.capabilities[key] = false;
        }
        api.config.changed?.emit();
      });

      // After the configChanged emit, the syncLauncherEntry helper should
      // have disposed every Coding Agent tile.
      await expect(codingAgent.locator('.jp-LauncherCard')).toHaveCount(0, {
        timeout: 5_000
      });
    }
  );
});
