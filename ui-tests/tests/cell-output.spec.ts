/**
 * Cell-output hover toolbar. Three action buttons (Explain / Ask /
 * Troubleshoot) mount inside the cell's `.jp-Cell-outputArea` when the
 * user hovers the output region. Troubleshoot is gated on the output
 * actually containing an error (cellOutputHasError in src/utils.ts).
 *
 * The toolbar mounts dynamically on hover, so the test has to drive a
 * real mouse-over before asserting. Galata exposes page.mouse + locator
 * .hover() which suffice.
 */
import { expect, test } from '@jupyterlab/galata';

test.describe('cell output hover toolbar', () => {
  test('renders Explain + Ask on a successful cell', async ({ page }) => {
    await page.notebook.createNew('cell-output-success.ipynb');
    await page.notebook.setCell(0, 'code', 'print("hello")');
    await page.notebook.run();

    const outputArea = page.locator('.jp-Cell-outputArea').first();
    await expect(outputArea).toBeVisible({ timeout: 15_000 });
    await outputArea.hover();

    const toolbar = page.locator('.nbi-cell-output-toolbar').first();
    await expect(toolbar).toBeVisible();
    const buttons = toolbar.locator('.nbi-cell-output-toolbar-button');
    // No troubleshoot button on a clean output.
    await expect(buttons).toHaveCount(2);
  });

  test('renders Troubleshoot when the cell errored', async ({ page }) => {
    // Regression guard for #229 follow-ups: cellOutputHasError used to
    // resolve through `.toJSON()` and miss the `output_type === 'error'`
    // case in some kernels. The fix iterates the model directly.
    await page.notebook.createNew('cell-output-error.ipynb');
    await page.notebook.setCell(0, 'code', '1 / 0');
    await page.notebook.run();

    const outputArea = page.locator('.jp-Cell-outputArea').first();
    await expect(outputArea).toBeVisible({ timeout: 15_000 });
    await outputArea.hover();

    const toolbar = page.locator('.nbi-cell-output-toolbar').first();
    await expect(toolbar).toBeVisible();
    const troubleshoot = toolbar.locator('[aria-label*="roubleshoot"]');
    await expect(troubleshoot).toHaveCount(1);
  });

  test('toolbar action activates the hovered cell', async ({ page }) => {
    // Regression guard: the click handler must set
    // activeCellIndex on the hovered cell BEFORE executing the command,
    // otherwise the command runs against whichever cell currently holds
    // focus. The stopPropagation on the click is load-bearing too — without
    // it, the parent cell click resets activeCellIndex back to 0.
    await page.notebook.createNew('cell-output-active.ipynb');
    await page.notebook.setCell(0, 'code', 'print("a")');
    await page.notebook.addCell('code', 'print("b")');
    await page.notebook.addCell('code', 'print("c")');
    await page.notebook.run();

    // Hover the third cell's output. Cell indices are 0-based.
    const outputs = page.locator('.jp-Cell-outputArea');
    await expect(outputs).toHaveCount(3);
    await outputs.nth(2).hover();

    const toolbar = page.locator('.nbi-cell-output-toolbar').first();
    await expect(toolbar).toBeVisible();
    // Click the "Explain" button (first in the action set).
    await toolbar.locator('.nbi-cell-output-toolbar-button').first().click();

    // Assert active cell moved to index 2.
    const activeIndex = await page.evaluate(() => {
      const app = (
        window as unknown as {
          jupyterapp?: {
            shell?: {
              currentWidget?: { content?: { activeCellIndex?: number } };
            };
          };
        }
      ).jupyterapp;
      return app?.shell?.currentWidget?.content?.activeCellIndex;
    });
    expect(activeIndex).toBe(2);
  });
});
