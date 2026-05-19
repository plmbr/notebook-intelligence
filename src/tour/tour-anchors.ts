// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

/**
 * Anchor-id constants shared between the tour step definitions and the
 * chat-sidebar JSX. Centralising these keeps the two halves coupled at
 * the TypeScript level rather than by string identity — a typo on
 * either side now surfaces at compile time instead of silently
 * skipping a step at runtime.
 */
export const TOUR_ANCHOR = {
  newChat: 'new-chat',
  settingsGear: 'settings-gear',
  claudeHistory: 'claude-history',
  slashCommands: 'slash-commands',
  addContext: 'add-context',
  uploadFile: 'upload-file',
  promptInput: 'prompt-input',
  chatMode: 'chat-mode'
} as const;

export type TourAnchorId = (typeof TOUR_ANCHOR)[keyof typeof TOUR_ANCHOR];
