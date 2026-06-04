// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import {
  removeAnsiChars,
  moveCodeSectionBoundaryMarkersToNewLine,
  extractLLMGeneratedCode,
  markdownToComment,
  compareSelectionPoints,
  compareSelections,
  isSelectionEmpty,
  isDarkTheme,
  getTokenCount,
  cellOutputAsText,
  applyCodeToSelectionInEditor,
  buildResumeCommand,
  hasDangerousTextCodepoints,
  safeAnchorUri,
  shellSingleQuote,
  writeTextToClipboard
} from '../../src/utils';

describe('removeAnsiChars', () => {
  it('strips colour escape sequences', () => {
    const colored = '\u001b[31merror\u001b[0m: oops';
    expect(removeAnsiChars(colored)).toBe('error: oops');
  });

  it('strips cursor-control escape sequences', () => {
    expect(removeAnsiChars('hi\u001b[2Athere')).toBe('hithere');
  });

  it('returns plain strings unchanged', () => {
    expect(removeAnsiChars('plain text')).toBe('plain text');
  });

  it('handles empty input', () => {
    expect(removeAnsiChars('')).toBe('');
  });
});

describe('moveCodeSectionBoundaryMarkersToNewLine', () => {
  it('splits an opening fence that has trailing content', () => {
    const input = '```pythonprint("hi")';
    expect(moveCodeSectionBoundaryMarkersToNewLine(input)).toBe(
      '```\nprint("hi")'
    );
  });

  it('splits a fence that opens and closes on a single line', () => {
    const input = '```pythonprint("hi")```';
    expect(moveCodeSectionBoundaryMarkersToNewLine(input)).toBe(
      '```\nprint("hi")\n```'
    );
  });

  it('drops a redundant language tag when nothing follows it', () => {
    expect(moveCodeSectionBoundaryMarkersToNewLine('```python')).toBe('```');
  });

  it('moves a trailing fence onto its own line', () => {
    const input = 'print("hi")```';
    expect(moveCodeSectionBoundaryMarkersToNewLine(input)).toBe(
      'print("hi")\n```'
    );
  });

  it('strips a redundant python language tag from a well-formed fence', () => {
    const input = '```python\nprint("hi")\n```';
    expect(moveCodeSectionBoundaryMarkersToNewLine(input)).toBe(
      '```\nprint("hi")\n```'
    );
  });
});

describe('extractLLMGeneratedCode', () => {
  it('extracts the body between matched fences', () => {
    const wrapped = '```python\nprint("hi")\n```';
    expect(extractLLMGeneratedCode(wrapped)).toBe('print("hi")\n');
  });

  it('extracts the body when only an opening fence is present', () => {
    const wrapped = '```python\nprint("hi")\nmore code';
    expect(extractLLMGeneratedCode(wrapped)).toBe('print("hi")\nmore code');
  });

  it('strips a trailing fence even without an opening fence', () => {
    expect(extractLLMGeneratedCode('print("hi")```')).toBe('print("hi")');
  });

  it('passes plain code through unchanged', () => {
    expect(extractLLMGeneratedCode('print("hi")')).toBe('print("hi")');
  });

  it('passes single-line input through unchanged', () => {
    expect(extractLLMGeneratedCode('one line')).toBe('one line');
  });

  it('tolerates leading whitespace before the fence', () => {
    const wrapped = '   ```\nprint("hi")\n```';
    expect(extractLLMGeneratedCode(wrapped)).toBe('print("hi")\n');
  });
});

describe('markdownToComment', () => {
  it('prefixes every line with "# "', () => {
    expect(markdownToComment('one\ntwo')).toBe('# one\n# two');
  });

  it('prefixes blank lines too', () => {
    expect(markdownToComment('one\n\ntwo')).toBe('# one\n# \n# two');
  });

  it('handles a single-line input', () => {
    expect(markdownToComment('hello')).toBe('# hello');
  });
});

describe('compareSelectionPoints', () => {
  it('returns true when both line and column match', () => {
    expect(
      compareSelectionPoints({ line: 1, column: 2 }, { line: 1, column: 2 })
    ).toBe(true);
  });

  it('returns false when lines differ', () => {
    expect(
      compareSelectionPoints({ line: 1, column: 2 }, { line: 2, column: 2 })
    ).toBe(false);
  });

  it('returns false when columns differ', () => {
    expect(
      compareSelectionPoints({ line: 1, column: 2 }, { line: 1, column: 3 })
    ).toBe(false);
  });
});

describe('compareSelections', () => {
  const range = (sl: number, sc: number, el: number, ec: number) => ({
    start: { line: sl, column: sc },
    end: { line: el, column: ec }
  });

  it('returns true for two selections with matching endpoints', () => {
    expect(compareSelections(range(0, 0, 1, 2), range(0, 0, 1, 2))).toBe(true);
  });

  it('returns false when endpoints differ', () => {
    expect(compareSelections(range(0, 0, 1, 2), range(0, 0, 1, 3))).toBe(false);
  });

  it('returns true when both selections are undefined', () => {
    expect(compareSelections(undefined as any, undefined as any)).toBe(true);
  });

  it('returns true when exactly one side is undefined', () => {
    expect(compareSelections(undefined as any, range(0, 0, 1, 2))).toBe(true);
    expect(compareSelections(range(0, 0, 1, 2), undefined as any)).toBe(true);
  });
});

describe('isSelectionEmpty', () => {
  it('returns true for a zero-length selection', () => {
    expect(
      isSelectionEmpty({
        start: { line: 3, column: 5 },
        end: { line: 3, column: 5 }
      })
    ).toBe(true);
  });

  it('returns false when the selection spans columns', () => {
    expect(
      isSelectionEmpty({
        start: { line: 3, column: 5 },
        end: { line: 3, column: 9 }
      })
    ).toBe(false);
  });

  it('returns false when the selection spans lines', () => {
    expect(
      isSelectionEmpty({
        start: { line: 3, column: 5 },
        end: { line: 4, column: 5 }
      })
    ).toBe(false);
  });
});

describe('applyCodeToSelectionInEditor', () => {
  const makeEditor = (dispatch?: jest.Mock) => {
    const updateSource = jest.fn();
    const setCursorPosition = jest.fn();
    const editor: any = {
      getSelection: jest.fn(() => ({
        start: { line: 0, column: 1 },
        end: { line: 0, column: 4 }
      })),
      getOffsetAt: jest.fn(position => position.column),
      getPositionAt: jest.fn(offset => ({ line: 0, column: offset })),
      lineCount: 1,
      getLine: jest.fn(() => 'abcXYZdef'),
      setCursorPosition,
      model: {
        sharedModel: {
          updateSource
        }
      }
    };
    if (dispatch) {
      editor.editor = { dispatch };
    }
    return { editor, updateSource, setCursorPosition };
  };

  it('uses CodeMirror dispatch when available so edits enter the undo path', () => {
    const dispatch = jest.fn();
    const { editor, updateSource, setCursorPosition } = makeEditor(dispatch);

    applyCodeToSelectionInEditor(editor, 'XYZ');

    expect(dispatch).toHaveBeenCalledWith({
      changes: { from: 1, to: 4, insert: 'XYZ' },
      selection: { anchor: 4 },
      scrollIntoView: true
    });
    expect(updateSource).not.toHaveBeenCalled();
    expect(setCursorPosition).toHaveBeenCalledWith({
      line: 0,
      column: 'abcXYZdef'.length
    });
  });

  it('falls back to shared model updates for non-CodeMirror editors', () => {
    const { editor, updateSource } = makeEditor();

    applyCodeToSelectionInEditor(editor, 'XYZ');

    expect(updateSource).toHaveBeenCalledWith(1, 4, 'XYZ');
  });
});

describe('isDarkTheme', () => {
  afterEach(() => {
    document.body.removeAttribute('data-jp-theme-light');
  });

  it('returns true when JupyterLab marks the theme as not light', () => {
    document.body.setAttribute('data-jp-theme-light', 'false');
    expect(isDarkTheme()).toBe(true);
  });

  it('returns false when the theme is light', () => {
    document.body.setAttribute('data-jp-theme-light', 'true');
    expect(isDarkTheme()).toBe(false);
  });

  it('returns false when the attribute is missing', () => {
    expect(isDarkTheme()).toBe(false);
  });
});

describe('getTokenCount', () => {
  it('returns 0 for empty input', () => {
    expect(getTokenCount('')).toBe(0);
  });

  it('returns a positive count that grows with input length', () => {
    const shorter = getTokenCount('one two');
    const longer = getTokenCount('one two three four five');
    expect(shorter).toBeGreaterThan(0);
    expect(longer).toBeGreaterThan(shorter);
  });
});

describe('cellOutputAsText', () => {
  // cellOutputAsText only touches `cell.outputArea.model.toJSON()`, so a
  // duck-typed stub avoids pulling in the JupyterLab cell widget machinery.
  const makeCell = (outputs: any[]) =>
    ({
      outputArea: { model: { toJSON: () => outputs } }
    }) as any;

  it('returns the empty string for a cell with no outputs', () => {
    expect(cellOutputAsText(makeCell([]))).toBe('');
  });

  it('renders execute_result text/plain payloads', () => {
    const cell = makeCell([
      {
        output_type: 'execute_result',
        data: { 'text/plain': '42' }
      }
    ]);
    expect(cellOutputAsText(cell)).toBe('42');
  });

  it('renders stream output with a trailing newline', () => {
    const cell = makeCell([{ output_type: 'stream', text: 'hello world' }]);
    expect(cellOutputAsText(cell)).toBe('hello world\n');
  });

  it('renders error output with name, value, and ansi-stripped traceback', () => {
    const cell = makeCell([
      {
        output_type: 'error',
        ename: 'ValueError',
        evalue: 'bad input',
        traceback: ['\u001b[31mTraceback line 1\u001b[0m', 'Traceback line 2']
      }
    ]);
    expect(cellOutputAsText(cell)).toBe(
      'ValueError: bad input\nTraceback line 1\nTraceback line 2\n'
    );
  });

  it('skips error output when traceback is missing', () => {
    const cell = makeCell([
      {
        output_type: 'error',
        ename: 'ValueError',
        evalue: 'bad input',
        traceback: undefined
      }
    ]);
    expect(cellOutputAsText(cell)).toBe('');
  });

  it('concatenates outputs of mixed types', () => {
    const cell = makeCell([
      { output_type: 'stream', text: 'first' },
      {
        output_type: 'execute_result',
        data: { 'text/plain': 'second' }
      }
    ]);
    expect(cellOutputAsText(cell)).toBe('first\nsecond');
  });

  // nbformat allows stream `text` and `data['text/plain']` to be a list of
  // strings joined with the empty string. Plain `String([...])` would coerce
  // that to a comma-joined garbage string.
  it('joins array-form stream text without comma separators', () => {
    const cell = makeCell([
      {
        output_type: 'stream',
        text: ['line one\n', 'line two\n', 'line three']
      }
    ]);
    expect(cellOutputAsText(cell)).toBe('line one\nline two\nline three\n');
  });

  it('joins array-form text/plain in execute_result', () => {
    const cell = makeCell([
      {
        output_type: 'execute_result',
        data: { 'text/plain': ['hello', '\n', 'world'] }
      }
    ]);
    expect(cellOutputAsText(cell)).toBe('hello\nworld');
  });
});

describe('writeTextToClipboard', () => {
  const originalClipboard = (navigator as any).clipboard;
  const originalExecCommand = (document as any).execCommand;

  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      configurable: true,
      writable: true
    });
    Object.defineProperty(document, 'execCommand', {
      value: originalExecCommand,
      configurable: true,
      writable: true
    });
  });

  it('writes via the async Clipboard API when available', async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true
    });

    const ok = await writeTextToClipboard('abc-123');

    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith('abc-123');
  });

  it('falls back to execCommand when the Clipboard API rejects', async () => {
    const writeText = jest.fn().mockRejectedValue(new Error('denied'));
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true
    });
    const execSpy = jest.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      value: execSpy,
      configurable: true,
      writable: true
    });

    const ok = await writeTextToClipboard('fallback-id');

    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith('fallback-id');
    expect(execSpy).toHaveBeenCalledWith('copy');
  });

  it('falls back to execCommand when the Clipboard API is missing', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
      writable: true
    });
    const execSpy = jest.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      value: execSpy,
      configurable: true,
      writable: true
    });

    const ok = await writeTextToClipboard('missing-api-id');

    expect(ok).toBe(true);
    expect(execSpy).toHaveBeenCalledWith('copy');
  });

  it('returns false when both paths fail', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
      writable: true
    });
    const execSpy = jest.fn().mockReturnValue(false);
    Object.defineProperty(document, 'execCommand', {
      value: execSpy,
      configurable: true,
      writable: true
    });

    const ok = await writeTextToClipboard('nope');

    expect(ok).toBe(false);
  });
});

describe('shellSingleQuote', () => {
  it('wraps a plain string in single quotes', () => {
    expect(shellSingleQuote('hello')).toBe("'hello'");
  });

  it('preserves spaces and slashes verbatim inside the quotes', () => {
    expect(shellSingleQuote('/Users/me/My Project')).toBe(
      "'/Users/me/My Project'"
    );
  });

  it('escapes embedded single quotes via close-escape-reopen', () => {
    // Apostrophe → close-quote, escaped literal, re-open-quote.
    expect(shellSingleQuote("it's")).toBe("'it'\\''s'");
  });

  it('handles multiple embedded quotes', () => {
    expect(shellSingleQuote("a'b'c")).toBe("'a'\\''b'\\''c'");
  });

  it('handles an empty string', () => {
    expect(shellSingleQuote('')).toBe("''");
  });
});

describe('buildResumeCommand', () => {
  it('wraps cd around the resume invocation when cwd is provided', () => {
    expect(buildResumeCommand('/tmp/proj', 'abc-123')).toBe(
      "cd '/tmp/proj' && claude --resume 'abc-123'"
    );
  });

  it('quotes paths with spaces correctly', () => {
    expect(buildResumeCommand('/Users/me/My Project', 'xyz')).toBe(
      "cd '/Users/me/My Project' && claude --resume 'xyz'"
    );
  });

  it('quotes session ids before shell interpolation', () => {
    expect(buildResumeCommand('/tmp/proj', "abc'; touch /tmp/pwned; '")).toBe(
      "cd '/tmp/proj' && claude --resume 'abc'\\''; touch /tmp/pwned; '\\'''"
    );
  });

  it('falls back to a bare resume when cwd is empty', () => {
    expect(buildResumeCommand('', 'abc-123')).toBe("claude --resume 'abc-123'");
  });
});

describe('safeAnchorUri', () => {
  it('accepts https URLs', () => {
    expect(safeAnchorUri('https://example.com/page')).toBe(
      'https://example.com/page'
    );
  });

  it('accepts http URLs', () => {
    expect(safeAnchorUri('http://example.com/')).toBe('http://example.com/');
  });

  it('accepts mailto links', () => {
    expect(safeAnchorUri('mailto:bob@example.com')).toBe(
      'mailto:bob@example.com'
    );
  });

  it('is case-insensitive on the scheme', () => {
    expect(safeAnchorUri('HTTPS://Example.COM/Path')).toBe(
      'HTTPS://Example.COM/Path'
    );
  });

  it('rejects javascript: URLs', () => {
    expect(safeAnchorUri('javascript:alert(1)')).toBeNull();
  });

  it('rejects data: URLs', () => {
    expect(
      safeAnchorUri('data:text/html,<script>alert(1)</script>')
    ).toBeNull();
  });

  it('rejects vbscript: URLs', () => {
    expect(safeAnchorUri('vbscript:msgbox(1)')).toBeNull();
  });

  it('rejects file: URLs', () => {
    expect(safeAnchorUri('file:///etc/passwd')).toBeNull();
  });

  it('rejects blob: URLs', () => {
    expect(safeAnchorUri('blob:https://example.com/abc')).toBeNull();
  });

  it('rejects URIs with C0 control characters that browsers may strip', () => {
    expect(safeAnchorUri('java\tscript:alert(1)')).toBeNull();
    expect(safeAnchorUri('javascript\n:alert(1)')).toBeNull();
    expect(safeAnchorUri('java\x00script:alert(1)')).toBeNull();
  });

  it('rejects URIs containing unicode format / zero-width / bidi marks', () => {
    expect(safeAnchorUri('https://example.com/\u0085')).toBeNull(); // NEL
    expect(safeAnchorUri('https://example.com/\u00a0')).toBeNull(); // NBSP
    expect(safeAnchorUri('https://example.com/\u2028')).toBeNull(); // LS
    expect(safeAnchorUri('https://example.com/\u2029')).toBeNull(); // PS
    expect(safeAnchorUri('https://example.com/\ufeff')).toBeNull(); // BOM
    expect(safeAnchorUri('https://example.com/\u200b')).toBeNull(); // ZWSP
    expect(safeAnchorUri('https://example.com/\u200e')).toBeNull(); // LRM
    expect(safeAnchorUri('https://example.com/\u202e')).toBeNull(); // RLO
    expect(safeAnchorUri('https://example.com/\u2066')).toBeNull(); // LRI
    expect(safeAnchorUri('https://example.com/\u0080')).toBeNull(); // C1
  });

  it('rejects empty / whitespace / non-string input', () => {
    expect(safeAnchorUri('')).toBeNull();
    expect(safeAnchorUri('   ')).toBeNull();
    expect(safeAnchorUri(undefined)).toBeNull();
    expect(safeAnchorUri(null)).toBeNull();
  });

  it('rejects relative paths without an allowed scheme', () => {
    expect(safeAnchorUri('/api/contents/secret.json')).toBeNull();
    expect(safeAnchorUri('../etc/passwd')).toBeNull();
    expect(safeAnchorUri('#section')).toBeNull();
    expect(safeAnchorUri('foo.txt')).toBeNull();
  });

  it('trims surrounding whitespace before validating', () => {
    expect(safeAnchorUri('   https://example.com/   ')).toBe(
      'https://example.com/'
    );
  });

  it('rejects CRLF injection inside an otherwise valid URI', () => {
    expect(safeAnchorUri('https://example.com/\r\nfoo')).toBeNull();
    expect(safeAnchorUri('https://example.com/\nfoo')).toBeNull();
  });

  it('rejects URIs above the 8 KiB length cap', () => {
    const longPath = 'x'.repeat(8200);
    expect(safeAnchorUri(`https://example.com/${longPath}`)).toBeNull();
  });

  it('accepts a URI near but under the length cap', () => {
    const longPath = 'x'.repeat(8000);
    const uri = `https://example.com/${longPath}`;
    expect(safeAnchorUri(uri)).toBe(uri);
  });
});

describe('hasDangerousTextCodepoints', () => {
  it('returns false for ordinary text', () => {
    expect(hasDangerousTextCodepoints('hello world')).toBe(false);
    expect(hasDangerousTextCodepoints('a.b/c?d=1')).toBe(false);
  });

  it('returns false for empty / non-string input', () => {
    expect(hasDangerousTextCodepoints('')).toBe(false);
    expect(hasDangerousTextCodepoints(null)).toBe(false);
    expect(hasDangerousTextCodepoints(undefined)).toBe(false);
  });

  it.each([
    ['C0 control (tab)', '\t'],
    ['C0 control (LF)', '\n'],
    ['DEL', '\x7f'],
    ['C1 control', '\x85'],
    ['NBSP', '\u00A0'],
    ['line separator', '\u2028'],
    ['paragraph separator', '\u2029'],
    ['BOM', '\uFEFF'],
    ['zero-width space', '\u200B'],
    ['RTL override', '\u202E'],
    ['LRI', '\u2066']
  ])('returns true for %s', (_, s) => {
    expect(hasDangerousTextCodepoints(`safe${s}text`)).toBe(true);
  });
});
