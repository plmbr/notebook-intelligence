/**
 * Shared helpers for the NBI Galata suite. Keep this file thin and stable —
 * the more its API churns the more every spec churns with it.
 */
import { expect, Page } from '@playwright/test';

/**
 * Open the Notebook Intelligence chat sidebar and resolve once its root
 * widget is visible. Most specs lead with this so the assertion they
 * actually care about runs against a stable layout.
 */
export async function openChatSidebar(page: Page): Promise<void> {
  const sidebarTab = page.locator('[data-id="notebook-intelligence-tab"]');
  await expect(sidebarTab).toHaveCount(1, { timeout: 30_000 });
  // Idempotent: clicking an already-active tab is a no-op in Lumino.
  await sidebarTab.click();
  await expect(page.locator('.sidebar')).toBeVisible();
}

/**
 * Read a value off the `NBIAPI.config` singleton inside the page. Returns
 * `undefined` if NBIAPI hasn't booted yet (the tests should always wait
 * for the sidebar to render first, which guarantees activation).
 */
export async function readNbiConfig<T = unknown>(
  page: Page,
  property: string
): Promise<T | undefined> {
  return page.evaluate(prop => {
    const api = (
      window as unknown as { NBIAPI?: { config?: Record<string, unknown> } }
    ).NBIAPI;
    return api?.config?.[prop] as T | undefined;
  }, property);
}
