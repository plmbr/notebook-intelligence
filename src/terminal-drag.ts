// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import { Notification } from '@jupyterlab/apputils';
import { Widget } from '@lumino/widgets';

import { NBIAPI } from './api';
import { DragMode, formatForMode, invertMode } from './terminal-drag-format';

export type { DragMode } from './terminal-drag-format';
export { formatForMode, invertMode } from './terminal-drag-format';

// Structural types over `IMainAreaWidgetLike` and
// `ITerminalTracker`: @jupyterlab/terminal nests its own copies of
// @jupyterlab/apputils and @lumino/widgets, so the nominal types don't
// unify with our top-level ones. Capturing only what we touch keeps the
// module decoupled from that version skew and unit-testable without a
// real JupyterLab application context.
interface ITerminalWidgetLike {
  paste(text: string): void;
}

interface IDisposedSignalLike {
  connect(slot: () => void): void;
}

interface ITerminalToolbarLike {
  addItem(name: string, widget: Widget): boolean;
}

interface IMainAreaWidgetLike {
  node: HTMLElement;
  content: ITerminalWidgetLike;
  toolbar: ITerminalToolbarLike;
  disposed: IDisposedSignalLike;
}

interface ITerminalTrackerLike {
  widgetAdded: {
    connect(slot: (sender: unknown, widget: IMainAreaWidgetLike) => void): void;
  };
  forEach(fn: (widget: IMainAreaWidgetLike) => void): void;
}

// File-browser drag dispatches a Lumino lm-drop event carrying paths
// under this MIME (see node_modules/@jupyterlab/filebrowser/lib/listing.js).
const FILE_BROWSER_MIME = 'application/x-jupyter-icontents';

const DRAG_OVER_CLASS = 'nbi-terminal-drag-over';
const TOOLBAR_BUTTON_CLASS = 'nbi-terminal-drag-mode-button';

interface ITerminalDragState {
  mode: DragMode;
  dragDepth: number;
  cleanup: () => void;
}

const widgetState = new WeakMap<IMainAreaWidgetLike, ITerminalDragState>();

export interface ITerminalDragOptions {
  // Untyped on the public surface because @jupyterlab/terminal nests its
  // own copy of every Lumino/JL type; coercing inside keeps callers from
  // needing to know about the duplication.
  tracker: unknown;
  /**
   * Re-evaluated on each event so flipping the admin policy at runtime
   * (e.g. force-off via env at next reload) takes effect on listeners
   * that are already wired without needing to tear them down.
   */
  isEnabled: () => boolean;
}

export function attachTerminalDragDrop(options: ITerminalDragOptions): void {
  const tracker = options.tracker as ITerminalTrackerLike;
  const { isEnabled } = options;

  const wire = (widget: IMainAreaWidgetLike) => {
    if (widgetState.has(widget)) {
      return;
    }
    setupTerminal(widget, isEnabled);
  };

  tracker.forEach(wire);
  tracker.widgetAdded.connect((_, widget) => wire(widget));
}

function setupTerminal(
  widget: IMainAreaWidgetLike,
  isEnabled: () => boolean
): void {
  const host = widget.node;

  const state: ITerminalDragState = {
    mode: 'mention',
    dragDepth: 0,
    cleanup: () => {}
  };

  const inject = (paths: string[], shiftHeld: boolean) => {
    if (paths.length === 0) {
      return;
    }
    const effectiveMode = invertMode(state.mode, shiftHeld);
    widget.content.paste(`${formatForMode(paths, effectiveMode)} `);
  };

  const handleDragEnter = (event: DragEvent) => {
    if (!isEnabled() || !event.dataTransfer) {
      return;
    }
    if (!event.dataTransfer.types.includes('Files')) {
      return;
    }
    state.dragDepth += 1;
    host.classList.add(DRAG_OVER_CLASS);
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  const handleDragOver = (event: DragEvent) => {
    if (!isEnabled() || !event.dataTransfer) {
      return;
    }
    if (!event.dataTransfer.types.includes('Files')) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    event.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (event: DragEvent) => {
    if (!isEnabled()) {
      return;
    }
    state.dragDepth = Math.max(0, state.dragDepth - 1);
    if (state.dragDepth === 0) {
      host.classList.remove(DRAG_OVER_CLASS);
    }
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  const handleDrop = (event: DragEvent) => {
    if (!isEnabled()) {
      return;
    }
    state.dragDepth = 0;
    host.classList.remove(DRAG_OVER_CLASS);
    if (!event.dataTransfer) {
      return;
    }
    const files = Array.from(event.dataTransfer.files);
    if (files.length === 0) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    const shiftHeld = event.shiftKey;
    void uploadAndInject(files, shiftHeld, inject);
  };

  const handleLuminoDragEnter = (event: Event) => {
    if (!isEnabled() || !hasFileBrowserPaths(event)) {
      return;
    }
    state.dragDepth += 1;
    host.classList.add(DRAG_OVER_CLASS);
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  const handleLuminoDragOver = (event: Event) => {
    if (!isEnabled() || !hasFileBrowserPaths(event)) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    (event as unknown as { dropAction: string }).dropAction = 'copy';
  };

  const handleLuminoDragLeave = (event: Event) => {
    if (!isEnabled()) {
      return;
    }
    state.dragDepth = Math.max(0, state.dragDepth - 1);
    if (state.dragDepth === 0) {
      host.classList.remove(DRAG_OVER_CLASS);
    }
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  const handleLuminoDrop = (event: Event) => {
    if (!isEnabled() || !hasFileBrowserPaths(event)) {
      return;
    }
    const dragEvent = event as unknown as {
      mimeData: { getData: (key: string) => unknown };
      shiftKey: boolean;
      dropAction: string;
    };
    const paths = dragEvent.mimeData.getData(FILE_BROWSER_MIME);
    if (!Array.isArray(paths) || paths.length === 0) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    dragEvent.dropAction = 'copy';
    state.dragDepth = 0;
    host.classList.remove(DRAG_OVER_CLASS);
    inject(
      paths.filter((p): p is string => typeof p === 'string'),
      dragEvent.shiftKey
    );
  };

  host.addEventListener('dragenter', handleDragEnter, true);
  host.addEventListener('dragover', handleDragOver, true);
  host.addEventListener('dragleave', handleDragLeave, true);
  host.addEventListener('drop', handleDrop, true);
  host.addEventListener('lm-dragenter', handleLuminoDragEnter);
  host.addEventListener('lm-dragover', handleLuminoDragOver);
  host.addEventListener('lm-dragleave', handleLuminoDragLeave);
  host.addEventListener('lm-drop', handleLuminoDrop);

  const button = new TerminalDragModeButton('mention', () => {
    state.mode = state.mode === 'mention' ? 'raw' : 'mention';
    button.setMode(state.mode);
  });
  widget.toolbar.addItem('nbi-terminal-drag-mode', button);

  state.cleanup = () => {
    host.removeEventListener('dragenter', handleDragEnter, true);
    host.removeEventListener('dragover', handleDragOver, true);
    host.removeEventListener('dragleave', handleDragLeave, true);
    host.removeEventListener('drop', handleDrop, true);
    host.removeEventListener('lm-dragenter', handleLuminoDragEnter);
    host.removeEventListener('lm-dragover', handleLuminoDragOver);
    host.removeEventListener('lm-dragleave', handleLuminoDragLeave);
    host.removeEventListener('lm-drop', handleLuminoDrop);
  };

  widget.disposed.connect(() => {
    state.cleanup();
    widgetState.delete(widget);
  });

  widgetState.set(widget, state);
}

function hasFileBrowserPaths(event: Event): boolean {
  const mimeData = (
    event as unknown as { mimeData?: { hasData?: (key: string) => boolean } }
  ).mimeData;
  return mimeData?.hasData?.(FILE_BROWSER_MIME) === true;
}

async function uploadAndInject(
  files: File[],
  shiftHeld: boolean,
  inject: (paths: string[], shiftHeld: boolean) => void
): Promise<void> {
  const results = await Promise.allSettled(
    files.map(f => NBIAPI.uploadFile(f))
  );
  const paths: string[] = [];
  const failures: { name: string; reason: string }[] = [];
  results.forEach((result, index) => {
    const file = files[index];
    if (result.status === 'fulfilled') {
      paths.push(result.value.serverPath);
      return;
    }
    failures.push({
      name: file.name,
      reason: describeUploadError(result.reason)
    });
  });
  if (failures.length > 0) {
    // Inline in the toast so the user sees both what failed and why
    // (e.g. 413 from the size cap). Truncated to 3 entries; rest collapsed
    // into a "+ N more" footer to fit JL's 140-char notification limit.
    const head = failures
      .slice(0, 3)
      .map(f => `${f.name}: ${f.reason}`)
      .join('; ');
    const tail = failures.length > 3 ? ` (+${failures.length - 3} more)` : '';
    Notification.error(`Terminal drop upload failed for ${head}${tail}`);
  }
  inject(paths, shiftHeld);
}

function describeUploadError(reason: unknown): string {
  if (reason && typeof reason === 'object') {
    const r = reason as { message?: unknown; response?: { status?: number } };
    if (typeof r.message === 'string' && r.message.trim().length > 0) {
      return r.message;
    }
    if (r.response && typeof r.response.status === 'number') {
      return `HTTP ${r.response.status}`;
    }
  }
  return String(reason);
}

class TerminalDragModeButton extends Widget {
  private _button: HTMLButtonElement;
  private _onToggle: () => void;

  constructor(initialMode: DragMode, onToggle: () => void) {
    super();
    this.addClass('jp-Toolbar-item');
    this.addClass(TOOLBAR_BUTTON_CLASS);
    this._onToggle = onToggle;

    this._button = document.createElement('button');
    this._button.type = 'button';
    this._button.classList.add('jp-ToolbarButtonComponent');
    this._button.classList.add(`${TOOLBAR_BUTTON_CLASS}-toggle`);
    this._button.addEventListener('click', () => this._onToggle());
    this.node.appendChild(this._button);

    this.setMode(initialMode);
  }

  setMode(mode: DragMode): void {
    const isMention = mode === 'mention';
    this._button.textContent = isMention ? '@' : '/';
    this._button.setAttribute('aria-pressed', isMention ? 'false' : 'true');
    // aria-label carries the full mode + Shift-modifier explanation;
    // title is a short hover-tip so screen readers don't double-announce
    // the same string from both attributes.
    this._button.setAttribute(
      'aria-label',
      isMention
        ? 'Terminal drop inserts @-mention paths. Click to switch to raw path mode. Hold Shift while dropping to invert for one drop.'
        : 'Terminal drop inserts raw, shell-escaped absolute paths. Click to switch to @-mention mode. Hold Shift while dropping to invert for one drop.'
    );
    this._button.title = isMention
      ? 'Drop mode: @-mention'
      : 'Drop mode: raw path';
  }
}
