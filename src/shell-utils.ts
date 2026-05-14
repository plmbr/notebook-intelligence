// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

/**
 * POSIX-shell single-quote escape: every embedded single quote is closed,
 * emitted as an escaped literal, and the quote re-opened. The result is
 * safe to splice into a shell command without further sanitization.
 */
export function shellSingleQuote(value: string): string {
  return "'" + value.replace(/'/g, "'\\''") + "'";
}
