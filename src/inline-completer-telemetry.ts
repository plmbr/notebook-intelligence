// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import type { IInlineCompleterFactory } from '@jupyterlab/completer';
import { ITelemetryEmitter, TelemetryEventType } from './tokens';

// Identifier of NBI's inline completion provider. Matches the package name and
// NBIInlineCompletionProvider.identifier; acceptance telemetry is only emitted
// when the accepted suggestion came from this provider.
export const NBI_INLINE_COMPLETION_PROVIDER_ID = '@plmbr/notebook-intelligence';

export interface IInlineCompletionModelInfo {
  provider: string;
  model: string;
}

// The inline completion provider interface has no accept callback, so the only
// reliable signal that a suggestion was taken is the inline completer widget's
// accept() method. Rather than subclass InlineCompleter (which would force us to
// reproduce all of JupyterLab's factory wiring: translator, toolbar buttons,
// keybinding hints), we wrap JupyterLab's own factory, let it build the
// fully-wired widget, and patch just the accept() method on the instance to emit
// acceptance telemetry for our own suggestions before delegating to the original.
// getModelInfo is read lazily at accept time so the event reflects the model
// configured when the suggestion was taken, not when the widget was created.
export function wrapInlineCompleterFactory(
  defaultFactory: IInlineCompleterFactory,
  telemetryEmitter: ITelemetryEmitter,
  getModelInfo: () => IInlineCompletionModelInfo
): IInlineCompleterFactory {
  return {
    factory: options => {
      const completer = defaultFactory.factory(options);
      const originalAccept = completer.accept.bind(completer);
      completer.accept = () => {
        const item = completer.current;
        if (item?.provider?.identifier === NBI_INLINE_COMPLETION_PROVIDER_ID) {
          telemetryEmitter.emitTelemetryEvent({
            type: TelemetryEventType.InlineCompletionAccepted,
            data: { inlineCompletionModel: getModelInfo() }
          });
        }
        originalAccept();
      };
      return completer;
    }
  };
}
