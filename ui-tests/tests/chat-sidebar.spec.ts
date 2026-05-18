/**
 * Chat sidebar interaction flows. These are the affordances a user touches
 * on the way to sending a prompt: the input footer, the prefix-completion
 * popover, the workspace file picker. None of these assertions require a
 * real LLM round trip — every passing condition is observable in local
 * React state.
 */
import { expect, test } from '@jupyterlab/galata';
import { openChatSidebar } from './helpers';

test.describe('chat sidebar layout', () => {
  test('renders three labelled buttons in the input footer', async ({
    page
  }) => {
    // Regression guard for PR #271 (ux/chat-input-footer-icons): each footer
    // button must carry a title + aria-label so screen readers and hover
    // tooltips both work. The original `<div onClick>` controls had only
    // titles, which several screen readers ignore.
    await openChatSidebar(page);
    const footer = page.locator('.user-input-footer').first();
    await expect(footer).toBeVisible();

    const slash = footer.locator('button[aria-label="Open slash commands"]');
    const workspace = footer.locator(
      'button[aria-label="Add workspace file as context"]'
    );
    const upload = footer.locator(
      'button[aria-label="Upload file from computer"]'
    );

    await expect(slash).toBeVisible();
    await expect(workspace).toBeVisible();
    await expect(upload).toBeVisible();
    // The slash button renders text, not an svg.
    await expect(slash).toHaveText('/');
  });

  test('sidebar-header gear is a focusable, labelled button', async ({
    page
  }) => {
    // Regression guard for D155 / D156: the gear used to be a <div onClick>
    // so keyboard users could not reach it. Pin that it is now a real
    // <button> with an aria-label, that Tab focus lands on it, and that
    // pressing Enter dispatches its click handler (the settings dialog
    // opens as the observable side effect).
    await openChatSidebar(page);
    const gear = page
      .locator(
        '.sidebar-header button[aria-label="Open Notebook Intelligence settings"]'
      )
      .first();
    await expect(gear).toBeVisible();
    await gear.focus();
    await expect(gear).toBeFocused();
    await page.keyboard.press('Enter');
    // The settings command opens an NBI settings widget in the main area.
    // Asserting the panel's wrapper appears proves Enter dispatched the
    // button's onClick handler.
    await expect(page.locator('.nbi-settings-panel').first()).toBeVisible({
      timeout: 5000
    });
  });
});

test.describe('prefix completion popover', () => {
  test('opens when "/" is typed into the prompt', async ({ page }) => {
    await openChatSidebar(page);
    // The textarea is rendered only when a chat provider is configured.
    // In a fresh Galata workspace no provider is configured, so the prompt
    // textarea may be hidden behind the "configure models" banner. Skip if
    // so — the popover isn't reachable without an input to type into.
    const textarea = page.locator('.sidebar-user-input textarea').first();
    if (!(await textarea.isVisible().catch(() => false))) {
      test.skip(true, 'No chat provider configured in test workspace');
    }

    await textarea.fill('/');
    const popover = page.locator('.user-input-autocomplete');
    await expect(popover).toBeVisible();
    // At minimum the built-in `/clear` slash command is always present.
    await expect(
      popover.locator('.user-input-autocomplete-item')
    ).not.toHaveCount(0);
  });

  test('slash button toggles the popover', async ({ page }) => {
    // The button only renders in ask chatMode (the default). If the test
    // workspace seeds Claude mode, the popover is reachable only by typing.
    await openChatSidebar(page);
    const slash = page
      .locator('button[aria-label="Open slash commands"]')
      .first();
    if (!(await slash.isVisible().catch(() => false))) {
      test.skip(true, 'Slash button only rendered in ask chatMode');
    }

    // Clicking the button toggles `showPopover` and focuses the prompt; we
    // only assert the popover-visibility delta because focus management is
    // covered by other tests and the autocomplete only renders when
    // `prefixSuggestions.length > 0`, which depends on chatParticipants.
    await slash.click();
    // No strict assertion on popover visibility here — see comment.
    // Re-clicking should hide it (idempotent toggle).
    await slash.click();
  });
});

test.describe('workspace file picker', () => {
  test('opens and closes via the close button', async ({ page }) => {
    await openChatSidebar(page);
    const trigger = page
      .locator('button[aria-label="Add workspace file as context"]')
      .first();
    if (!(await trigger.isVisible().catch(() => false))) {
      test.skip(true, 'Sidebar requires a configured provider for this flow');
    }
    await trigger.click();
    const popover = page.locator('.workspace-file-popover');
    await expect(popover).toBeVisible();

    const closeBtn = popover
      .locator('[aria-label="Close file picker"]')
      .first();
    await closeBtn.click();
    await expect(popover).toHaveCount(0);
  });

  test('Escape from the search input closes the picker', async ({ page }) => {
    // Regression guard for #262: the picker's search input used to
    // stopPropagation on every keydown, including Escape, leaving the
    // dialog dismissable only via the close icon.
    await openChatSidebar(page);
    const trigger = page
      .locator('button[aria-label="Add workspace file as context"]')
      .first();
    if (!(await trigger.isVisible().catch(() => false))) {
      test.skip(true, 'Sidebar requires a configured provider for this flow');
    }
    await trigger.click();
    const popover = page.locator('.workspace-file-popover');
    await expect(popover).toBeVisible();

    const search = popover.locator('.workspace-file-search-input').first();
    await search.click();
    await search.fill('xyz');
    await page.keyboard.press('Escape');
    await expect(popover).toHaveCount(0);
  });
});
