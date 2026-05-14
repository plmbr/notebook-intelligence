// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import { formatForMode, invertMode } from '../../src/terminal-drag-format';

describe('formatForMode', () => {
  it('prefixes each path with @ in mention mode', () => {
    expect(formatForMode(['/tmp/a.txt', '/tmp/b.txt'], 'mention')).toBe(
      '@/tmp/a.txt @/tmp/b.txt'
    );
  });

  it('shell-escapes each path in raw mode', () => {
    expect(formatForMode(['/tmp/a.txt', '/tmp/with space.txt'], 'raw')).toBe(
      "'/tmp/a.txt' '/tmp/with space.txt'"
    );
  });

  it('returns empty string for empty input in either mode', () => {
    expect(formatForMode([], 'mention')).toBe('');
    expect(formatForMode([], 'raw')).toBe('');
  });

  it('handles a single path in mention mode', () => {
    expect(formatForMode(['/tmp/only.txt'], 'mention')).toBe('@/tmp/only.txt');
  });

  it('does not quote the @-prefix in mention mode', () => {
    // Intentional: Claude Code parses bare @<path> tokens, so wrapping them
    // in shell quotes would break the parse. Mention mode trusts the path
    // not to contain shell metacharacters; raw mode is the path that quotes.
    expect(formatForMode(['/tmp/a b.txt'], 'mention')).toBe('@/tmp/a b.txt');
  });
});

describe('invertMode', () => {
  it('returns the original mode when shouldInvert is false', () => {
    expect(invertMode('mention', false)).toBe('mention');
    expect(invertMode('raw', false)).toBe('raw');
  });

  it('flips mention to raw and back when shouldInvert is true', () => {
    expect(invertMode('mention', true)).toBe('raw');
    expect(invertMode('raw', true)).toBe('mention');
  });
});
