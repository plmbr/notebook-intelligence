import { expect, test } from '@jupyterlab/galata';

test.describe('notebook-intelligence extension', () => {
  test('lab loads with the labextension installed', async ({ page }) => {
    // Galata waits for lab's main shell to render before resolving the page
    // fixture, so by the time the test body runs the extension's
    // ``activate()`` hook should already have fired.
    const installed = await page.evaluate(() => {
      // The extension registers itself on window.jupyterapp via JupyterLab's
      // standard plugin system; presence of either the plugin id or the
      // labextension manifest entry is enough to confirm it loaded.
      const app = (window as any).jupyterapp;
      if (!app) {
        return false;
      }
      const ids: string[] = app.listPlugins();
      return ids.some((id: string) => id.startsWith('@plmbr/'));
    });
    expect(installed).toBe(true);
  });

  test('chat sidebar can be opened from the side panel', async ({ page }) => {
    // The sidebar tab id matches ``panel.id`` from src/index.ts; Lumino's
    // TabBar renders that into ``data-id`` on the tab list element. Asserting
    // ``toHaveCount(1)`` upfront makes a future renaming or duplicate id fail
    // with a clear error rather than ``.first()`` quietly picking one.
    const sidebarTab = page.locator('[data-id="notebook-intelligence-tab"]');
    await expect(sidebarTab).toHaveCount(1, { timeout: 30_000 });
    await expect(sidebarTab).toBeVisible();
    await sidebarTab.click();
    // ``.sidebar`` is the chat-sidebar root inside the panel; constrain the
    // assertion to a single visible match.
    const sidebar = page.locator('.sidebar');
    await expect(sidebar).toBeVisible();
  });
});
