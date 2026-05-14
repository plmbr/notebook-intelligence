// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

// Pure helpers extracted from `terminal-drag.ts` so they can be unit
// tested without JupyterLab / Lumino imports (which pull DOM globals
// that jsdom doesn't provide, like DragEvent).

import { shellSingleQuote } from './shell-utils';

export type DragMode = 'mention' | 'raw';

/**
 * Format a list of paths for injection per mode. @-mention prefixes each
 * path with "@" (Claude Code syntax, no quoting); raw mode shell-escapes
 * absolute paths for non-Claude shell sessions. Single-space separator
 * is intentional; the trailing space is appended by the caller.
 */
export function formatForMode(paths: string[], mode: DragMode): string {
  if (mode === 'mention') {
    return paths.map(p => `@${p}`).join(' ');
  }
  return paths.map(shellSingleQuote).join(' ');
}

export function invertMode(mode: DragMode, shouldInvert: boolean): DragMode {
  if (!shouldInvert) {
    return mode;
  }
  return mode === 'mention' ? 'raw' : 'mention';
}
