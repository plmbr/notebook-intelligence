// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import {
  attachOpenFileRefreshWatcher,
  IRefreshWatcherEnv,
  shouldRevertContext,
  WATCHED_SHELL_AREAS
} from '../../src/open-file-refresh-watcher';

describe('WATCHED_SHELL_AREAS', () => {
  it('excludes "down" because LabShell.widgets() throws on it at runtime', () => {
    // Regression pin for PR #330 review feedback (mbektas). 'down' is
    // present in JupyterLab's TypeScript Area union but absent from
    // LabShell.widgets()'s runtime switch; including it would throw
    // `Invalid area: down` and surface as an unhandled promise
    // rejection on every poll tick.
    expect(WATCHED_SHELL_AREAS).not.toContain('down');
  });

  it('includes "main" so the primary editor area is always covered', () => {
    expect(WATCHED_SHELL_AREAS).toContain('main');
  });

  it('contains only areas LabShell.widgets() implements', () => {
    // The runtime switch at @jupyterlab/application/lib/shell.js
    // handles: main, left, right, header, top, menu, bottom. We walk
    // the document-hosting subset (main, left, right); chrome areas
    // (header/top/menu/bottom) never host DocumentWidget. Pin the
    // exact set so a future widening that re-adds 'down' (or any
    // unimplemented area) trips this assertion.
    const RUNTIME_IMPLEMENTED = new Set([
      'main',
      'left',
      'right',
      'header',
      'top',
      'menu',
      'bottom'
    ]);
    for (const area of WATCHED_SHELL_AREAS) {
      expect(RUNTIME_IMPLEMENTED).toContain(area);
    }
  });
});

describe('shouldRevertContext', () => {
  const base = {
    isDirty: false,
    isReady: true,
    isDisposed: false,
    contextLastModified: '2026-01-01T00:00:00.000000Z',
    diskLastModified: '2026-01-01T00:00:00.000000Z'
  };

  it('reverts when disk is strictly newer than the context', () => {
    expect(
      shouldRevertContext({
        ...base,
        diskLastModified: '2026-01-01T00:00:01.000000Z'
      })
    ).toBe(true);
  });

  it('skips when timestamps match (already current)', () => {
    expect(shouldRevertContext(base)).toBe(false);
  });

  it('skips when disk is older (something rolled back the file)', () => {
    expect(
      shouldRevertContext({
        ...base,
        diskLastModified: '2025-12-31T23:59:59.000000Z'
      })
    ).toBe(false);
  });

  it('skips when the model is dirty so user edits are never clobbered', () => {
    // The standard Lab "newer on disk" prompt fires at save time and is
    // the right place to involve the user; the silent revert path
    // should defer to it.
    expect(
      shouldRevertContext({
        ...base,
        isDirty: true,
        diskLastModified: '2026-01-02T00:00:00.000000Z'
      })
    ).toBe(false);
  });

  it('skips when the context is not yet ready', () => {
    // Reverting before populate() finishes would race the initial
    // load and produce a spurious revert that re-fetches the same
    // bytes the context is already pulling.
    expect(
      shouldRevertContext({
        ...base,
        isReady: false,
        diskLastModified: '2026-01-02T00:00:00.000000Z'
      })
    ).toBe(false);
  });

  it('skips when the context is disposed', () => {
    expect(
      shouldRevertContext({
        ...base,
        isDisposed: true,
        diskLastModified: '2026-01-02T00:00:00.000000Z'
      })
    ).toBe(false);
  });

  it('skips when either timestamp is missing', () => {
    expect(
      shouldRevertContext({
        ...base,
        diskLastModified: undefined,
        contextLastModified: '2026-01-01T00:00:00.000000Z'
      })
    ).toBe(false);
    expect(
      shouldRevertContext({
        ...base,
        diskLastModified: '2026-01-01T00:00:00.000000Z',
        contextLastModified: null
      })
    ).toBe(false);
  });
});

interface IFakeContext {
  path: string;
  contentsModel: { last_modified: string } | null;
  model: { dirty: boolean };
  isReady: boolean;
  isDisposed: boolean;
  revert: jest.Mock<Promise<void>, []>;
}

interface IFakeWidget {
  context: IFakeContext;
}

function makeContext(overrides: Partial<IFakeContext> = {}): IFakeContext {
  return {
    path: 'notebook.ipynb',
    contentsModel: { last_modified: '2026-01-01T00:00:00.000000Z' },
    model: { dirty: false },
    isReady: true,
    isDisposed: false,
    revert: jest.fn().mockResolvedValue(undefined),
    ...overrides
  };
}

function makeEnv(
  widgets: IFakeWidget[],
  diskByPath: Record<string, string | Error>
): {
  env: IRefreshWatcherEnv;
  fireTick: () => Promise<void>;
} {
  let tickHandler: (() => void) | null = null;
  return {
    env: {
      iterDocumentWidgets: () => widgets,
      fetchDiskModel: async path => {
        const entry = diskByPath[path];
        if (entry instanceof Error) {
          throw entry;
        }
        if (entry === undefined) {
          throw new Error(`no fake disk entry for ${path}`);
        }
        return {
          name: path.split('/').pop() ?? path,
          path,
          type: 'file',
          writable: true,
          created: '2026-01-01T00:00:00.000000Z',
          last_modified: entry,
          mimetype: 'text/plain',
          content: null,
          format: null
        };
      },
      setInterval: handler => {
        tickHandler = handler;
        return 'fake-handle';
      },
      clearInterval: () => {
        tickHandler = null;
      }
    },
    fireTick: async () => {
      if (!tickHandler) {
        throw new Error('setInterval was never called');
      }
      tickHandler();
      // Tick runs an async loop; flush microtasks so jest assertions
      // see the post-tick state.
      await new Promise(resolve => setTimeout(resolve, 0));
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  };
}

describe('attachOpenFileRefreshWatcher', () => {
  it('reverts an open widget when its file is newer on disk', async () => {
    const ctx = makeContext();
    const { env, fireTick } = makeEnv([{ context: ctx }], {
      'notebook.ipynb': '2026-01-01T00:00:05.000000Z'
    });
    const onRevert = jest.fn();
    attachOpenFileRefreshWatcher({ env, isEnabled: () => true, onRevert });

    await fireTick();

    expect(ctx.revert).toHaveBeenCalledTimes(1);
    expect(onRevert).toHaveBeenCalledWith('notebook.ipynb');
  });

  it('does not call revert when the toggle is disabled', async () => {
    const ctx = makeContext();
    const { env, fireTick } = makeEnv([{ context: ctx }], {
      'notebook.ipynb': '2026-01-01T00:00:05.000000Z'
    });
    let enabled = false;
    attachOpenFileRefreshWatcher({ env, isEnabled: () => enabled });

    await fireTick();
    expect(ctx.revert).not.toHaveBeenCalled();

    enabled = true;
    await fireTick();
    expect(ctx.revert).toHaveBeenCalledTimes(1);
  });

  it('dedupes by path so split-view widgets do not double-revert', async () => {
    // A notebook plus its console-view share one context; the revert
    // should fire once per shared context, not once per widget.
    const ctx = makeContext();
    const { env, fireTick } = makeEnv([{ context: ctx }, { context: ctx }], {
      'notebook.ipynb': '2026-01-01T00:00:05.000000Z'
    });
    attachOpenFileRefreshWatcher({ env, isEnabled: () => true });

    await fireTick();
    expect(ctx.revert).toHaveBeenCalledTimes(1);
  });

  it('skips dirty contexts so user edits survive a tick', async () => {
    const ctx = makeContext({ model: { dirty: true } });
    const { env, fireTick } = makeEnv([{ context: ctx }], {
      'notebook.ipynb': '2026-01-01T00:00:05.000000Z'
    });
    attachOpenFileRefreshWatcher({ env, isEnabled: () => true });

    await fireTick();
    expect(ctx.revert).not.toHaveBeenCalled();
  });

  it('reports per-path errors instead of throwing out of the tick', async () => {
    const ctx = makeContext();
    const { env, fireTick } = makeEnv([{ context: ctx }], {
      'notebook.ipynb': new Error('404 file deleted')
    });
    const onError = jest.fn();
    attachOpenFileRefreshWatcher({ env, isEnabled: () => true, onError });

    await fireTick();

    expect(onError).toHaveBeenCalledWith('notebook.ipynb', expect.any(Error));
    expect(ctx.revert).not.toHaveBeenCalled();
  });

  it('skips a tick that fires while the previous one is still in flight', async () => {
    // Pin the re-entrancy guard: a slow Contents.get must not let the
    // next interval-fired tick pile up checks against the same set of
    // widgets. Without the guard, two overlapping ticks would each
    // call revert() on the same already-newer file.
    const ctx = makeContext();
    let release: (() => void) | null = null;
    const fetchDiskModel = jest.fn().mockImplementation(
      () =>
        new Promise<{
          name: string;
          path: string;
          type: string;
          writable: boolean;
          created: string;
          last_modified: string;
          mimetype: string;
          content: null;
          format: null;
        }>(resolve => {
          release = () =>
            resolve({
              name: 'notebook.ipynb',
              path: 'notebook.ipynb',
              type: 'file',
              writable: true,
              created: '2026-01-01T00:00:00.000000Z',
              last_modified: '2026-01-01T00:00:05.000000Z',
              mimetype: 'text/plain',
              content: null,
              format: null
            });
        })
    );
    let tickHandler: (() => void) | null = null;
    const env: IRefreshWatcherEnv = {
      iterDocumentWidgets: () => [{ context: ctx }],
      fetchDiskModel,
      setInterval: handler => {
        tickHandler = handler;
        return 'h';
      },
      clearInterval: () => {
        tickHandler = null;
      }
    };
    attachOpenFileRefreshWatcher({ env, isEnabled: () => true });

    tickHandler!();
    // Second tick fires while the first is still awaiting the fetch.
    tickHandler!();
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(fetchDiskModel).toHaveBeenCalledTimes(1);

    release!();
    await new Promise(resolve => setTimeout(resolve, 0));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(ctx.revert).toHaveBeenCalledTimes(1);
  });

  it('reports revert() rejections via onError', async () => {
    // Disk-newer decision passes, revert() then throws (e.g. file
    // deleted between the disk-check and the revert call). The error
    // must land in onError, not bubble out and kill the poller.
    const ctx = makeContext();
    ctx.revert.mockRejectedValueOnce(new Error('file vanished'));
    const { env, fireTick } = makeEnv([{ context: ctx }], {
      'notebook.ipynb': '2026-01-01T00:00:05.000000Z'
    });
    const onError = jest.fn();
    const onRevert = jest.fn();
    attachOpenFileRefreshWatcher({
      env,
      isEnabled: () => true,
      onError,
      onRevert
    });

    await fireTick();

    expect(ctx.revert).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith('notebook.ipynb', expect.any(Error));
    // onRevert must not have fired since the revert call itself failed.
    expect(onRevert).not.toHaveBeenCalled();
  });

  it('skips revert when dirty flips during the in-flight disk fetch', async () => {
    // Property test: when the model goes dirty between the start of
    // the disk fetch and the decision point, the watcher backs off.
    // (The initial dirty check inside shouldRevertContext is the
    // load-bearing guard for this scenario; the post-decision
    // re-check is documented as defense-in-depth in the production
    // file. Either guard alone would satisfy this test.)
    const ctx = makeContext();
    let release: (() => void) | null = null;
    const fetchDiskModel = jest.fn().mockImplementation(
      () =>
        new Promise<{
          name: string;
          path: string;
          type: string;
          writable: boolean;
          created: string;
          last_modified: string;
          mimetype: string;
          content: null;
          format: null;
        }>(resolve => {
          release = () =>
            resolve({
              name: 'notebook.ipynb',
              path: 'notebook.ipynb',
              type: 'file',
              writable: true,
              created: '2026-01-01T00:00:00.000000Z',
              last_modified: '2026-01-01T00:00:05.000000Z',
              mimetype: 'text/plain',
              content: null,
              format: null
            });
        })
    );
    let tickHandler: (() => void) | null = null;
    const env: IRefreshWatcherEnv = {
      iterDocumentWidgets: () => [{ context: ctx }],
      fetchDiskModel,
      setInterval: handler => {
        tickHandler = handler;
        return 'h';
      },
      clearInterval: () => {
        tickHandler = null;
      }
    };
    attachOpenFileRefreshWatcher({ env, isEnabled: () => true });

    tickHandler!();
    // Simulate a keystroke arriving while the disk fetch is in flight.
    ctx.model.dirty = true;
    release!();
    await new Promise(resolve => setTimeout(resolve, 0));
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(ctx.revert).not.toHaveBeenCalled();
  });

  it('clears the interval and no longer runs ticks after teardown', async () => {
    let cleared = false;
    let tickHandler: (() => void) | null = null;
    const fetchDiskModel = jest.fn();
    const env: IRefreshWatcherEnv = {
      iterDocumentWidgets: () => [{ context: makeContext() }],
      fetchDiskModel,
      setInterval: handler => {
        tickHandler = handler;
        return 'h';
      },
      clearInterval: handle => {
        if (handle === 'h') {
          cleared = true;
        }
      }
    };
    const teardown = attachOpenFileRefreshWatcher({
      env,
      isEnabled: () => true
    });
    teardown();
    expect(cleared).toBe(true);
    // Invoke the captured tick handler directly to confirm any
    // straggling timer fire after clearInterval would still be inert.
    // (clearInterval is best-effort across browsers; the watcher's
    // post-teardown handler should not stat any contexts.)
    tickHandler!();
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(fetchDiskModel).not.toHaveBeenCalled();
  });
});
