/**
 * Notebook generation toolbar + popover. The button is inserted after the
 * cellType toolbar item; the popover hosts a textarea + checkbox + submit.
 *
 * Past regressions covered here:
 *   - #229 / PR #238: the button was gated on Claude mode and disappeared
 *     for Copilot users.
 *   - #231: clicking the button left the textarea unfocused on a fresh
 *     mount because the focus call ran before the element existed.
 *   - "disable NBI notebook toolbar if not in claude mode" (commit 871277d)
 *     introduced a re-render path that previously left the button stuck.
 */
import { expect, test } from '@jupyterlab/galata';

test.describe('notebook generation toolbar', () => {
  test('toolbar button renders on an open notebook', async ({ page }) => {
    await page.notebook.createNew('toolbar-button.ipynb');
    // The wrapper carries the class; the actual <button> with the title
    // attribute is a JL ToolbarButton child. Assert visibility on the
    // wrapper and the title on the inner <button>.
    const wrapper = page
      .locator('.nbi-notebook-generation-toolbar-button')
      .first();
    await expect(wrapper).toBeVisible({ timeout: 15_000 });
    // JL's ToolbarButton ships `aria-label` rather than `title`.
    await expect(wrapper.locator('button').first()).toHaveAttribute(
      'aria-label',
      /notebook|generate/i
    );
  });

  test('toolbar button opens a popover with the expected structure', async ({
    page
  }) => {
    await page.notebook.createNew('toolbar-popover.ipynb');
    await page
      .locator('.nbi-notebook-generation-toolbar-button')
      .first()
      .click();

    const popover = page.locator('.notebook-generation-popover').first();
    await expect(popover).toBeVisible();
    await expect(
      popover.locator('.notebook-generation-popover-input')
    ).toBeVisible();
    // The submit button starts disabled because the textarea is empty.
    const submit = popover
      .locator('.notebook-generation-popover-submit')
      .first();
    await expect(submit).toBeDisabled();
    // "Show in chat" toggle starts checked (the user opts out, not in).
    const showInChat = popover.locator('input[type="checkbox"]').first();
    if (await showInChat.count()) {
      await expect(showInChat).toBeChecked();
    }
  });

  test('popover textarea is focused on open', async ({ page }) => {
    // Regression guard for #231: the focus call used to run before the
    // popover element existed. The fix wraps it in a requestAnimationFrame.
    await page.notebook.createNew('toolbar-focus.ipynb');
    await page
      .locator('.nbi-notebook-generation-toolbar-button')
      .first()
      .click();

    const textarea = page
      .locator(
        '.notebook-generation-popover .notebook-generation-popover-input'
      )
      .first();
    await expect(textarea).toBeVisible();
    await expect(textarea).toBeFocused();
  });

  test('typing a prompt enables the submit button', async ({ page }) => {
    await page.notebook.createNew('toolbar-submit.ipynb');
    await page
      .locator('.nbi-notebook-generation-toolbar-button')
      .first()
      .click();

    const popover = page.locator('.notebook-generation-popover').first();
    const textarea = popover
      .locator('.notebook-generation-popover-input')
      .first();
    const submit = popover
      .locator('.notebook-generation-popover-submit')
      .first();
    await expect(submit).toBeDisabled();
    await textarea.fill('add a plot cell');
    await expect(submit).toBeEnabled();
  });

  test('Escape and outside-click both dismiss the popover', async ({
    page
  }) => {
    await page.notebook.createNew('toolbar-dismiss.ipynb');
    const button = page
      .locator('.nbi-notebook-generation-toolbar-button')
      .first();
    await button.click();
    const popover = page.locator('.notebook-generation-popover').first();
    await expect(popover).toBeVisible();
    // Wait for the rAF-deferred textarea focus to land before sending
    // Escape; pressing too early lands the keystroke on the body which
    // never reaches the popover's onKeyDown handler.
    const textarea = popover
      .locator('.notebook-generation-popover-input')
      .first();
    await expect(textarea).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(popover).toHaveCount(0);

    // Re-open + click outside.
    await button.click();
    const popover2 = page.locator('.notebook-generation-popover').first();
    await expect(popover2).toBeVisible();
    // Click the main menu bar — safely outside the popover.
    await page.locator('#jp-menu-panel').click({ force: true });
    await expect(page.locator('.notebook-generation-popover')).toHaveCount(0);
  });
});
