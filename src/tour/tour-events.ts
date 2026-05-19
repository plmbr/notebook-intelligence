// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

/**
 * Decoupled trigger channel for the first-run tour.
 *
 * The JupyterLab command (`notebook-intelligence:show-tour`) is
 * registered in `src/index.ts` so it shows up in the command palette
 * and can be invoked from anywhere. The tour itself is rendered inside
 * the chat sidebar (`src/chat-sidebar.tsx`) so it can access React
 * state cleanly. Wiring those two together via DOM CustomEvents keeps
 * index.ts free of any direct sidebar import and lets the tour be
 * triggered from any future surface (a Settings dialog entry, a Help
 * menu, a banner) by dispatching the same event.
 *
 * Dispatched on `document` to match the existing `copilotSidebar:*`
 * channel convention elsewhere in this codebase.
 */

export const TOUR_START_EVENT = 'nbi:show-tour';
export const TOUR_STOP_EVENT = 'nbi:hide-tour';

export function dispatchShowTour(): void {
  if (typeof document === 'undefined') {
    return;
  }
  document.dispatchEvent(new CustomEvent(TOUR_START_EVENT));
}

export function dispatchHideTour(): void {
  if (typeof document === 'undefined') {
    return;
  }
  document.dispatchEvent(new CustomEvent(TOUR_STOP_EVENT));
}
