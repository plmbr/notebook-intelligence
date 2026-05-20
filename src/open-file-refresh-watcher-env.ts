// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

// Live binding for the open-file refresh watcher. Lives in its own
// file so unit tests can exercise the pure logic in
// `open-file-refresh-watcher.ts` without transitively importing
// `@jupyterlab/docregistry`, which ships ESM that ts-jest's default
// transform can't parse.

import { JupyterFrontEnd } from '@jupyterlab/application';
import { DocumentWidget } from '@jupyterlab/docregistry';
import { Contents } from '@jupyterlab/services';

import {
  IRefreshWatcherEnv,
  WATCHED_SHELL_AREAS
} from './open-file-refresh-watcher';

export function buildRefreshWatcherEnv(
  app: JupyterFrontEnd,
  contents: Contents.IManager
): IRefreshWatcherEnv {
  return {
    iterDocumentWidgets: function* () {
      for (const area of WATCHED_SHELL_AREAS) {
        // Defensive try/catch: LabShell.widgets() throws for areas it
        // doesn't implement. We've audited the current set against
        // the runtime, but a future JL bump could rename or remove
        // an area; surfacing it as a console warning rather than an
        // unhandled rejection keeps the watcher running for the
        // areas that DO work.
        let widgets: Iterable<unknown>;
        try {
          widgets = app.shell.widgets(area);
        } catch (err) {
          console.warn(
            `[NBI] open-file-refresh-watcher: skipping shell area "${area}":`,
            err
          );
          continue;
        }
        for (const widget of widgets) {
          if (widget instanceof DocumentWidget) {
            yield widget;
          }
        }
      }
    },
    fetchDiskModel: path => contents.get(path, { content: false }),
    setInterval: (handler, ms) => window.setInterval(handler, ms),
    clearInterval: handle => window.clearInterval(handle as number)
  };
}
