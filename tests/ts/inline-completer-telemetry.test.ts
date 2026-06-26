// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import {
  wrapInlineCompleterFactory,
  NBI_INLINE_COMPLETION_PROVIDER_ID
} from '../../src/inline-completer-telemetry';
import { TelemetryEventType } from '../../src/tokens';

// Minimal stand-in for JupyterLab's InlineCompleter: only the surface the
// wrapper reads (`current`) and patches (`accept`). The fake's accept() clears
// `current` like the real widget does, which pins the load-bearing invariant
// that the wrapper reads `current` BEFORE delegating: were the read moved after
// originalAccept(), `current` would already be null and telemetry would silently
// vanish, yet a fake whose accept() left `current` intact would not catch it.
function makeCompleter(identifier?: string | null) {
  const completer = {
    current:
      identifier === undefined
        ? undefined
        : { provider: identifier === null ? undefined : { identifier } },
    accept: jest.fn()
  } as any;
  completer.accept.mockImplementation(() => {
    completer.current = null;
  });
  return completer;
}

function setup(identifier?: string | null) {
  const completer = makeCompleter(identifier);
  const originalAccept = completer.accept;
  const defaultFactory = { factory: jest.fn(() => completer) } as any;
  const emitter = { emitTelemetryEvent: jest.fn() };
  const modelInfo = { provider: 'openai-compatible', model: 'gpt-4o-mini' };
  const wrapped = wrapInlineCompleterFactory(
    defaultFactory,
    emitter,
    () => modelInfo
  );
  const returned = wrapped.factory({} as any);
  return {
    completer,
    originalAccept,
    defaultFactory,
    emitter,
    modelInfo,
    returned
  };
}

describe('wrapInlineCompleterFactory', () => {
  it('delegates widget construction to the wrapped factory', () => {
    const { defaultFactory, returned, completer } = setup(
      NBI_INLINE_COMPLETION_PROVIDER_ID
    );
    expect(defaultFactory.factory).toHaveBeenCalledTimes(1);
    // The wrapper returns the very widget the default factory built (so all of
    // JupyterLab's toolbar/translator wiring is preserved), not a replacement.
    expect(returned).toBe(completer);
  });

  it('emits acceptance telemetry for an NBI suggestion, then calls the original accept', () => {
    const { completer, originalAccept, emitter, modelInfo } = setup(
      NBI_INLINE_COMPLETION_PROVIDER_ID
    );

    completer.accept();

    expect(emitter.emitTelemetryEvent).toHaveBeenCalledTimes(1);
    expect(emitter.emitTelemetryEvent).toHaveBeenCalledWith({
      type: TelemetryEventType.InlineCompletionAccepted,
      data: { inlineCompletionModel: modelInfo }
    });
    expect(originalAccept).toHaveBeenCalledTimes(1);
    // Telemetry must be emitted before delegating, while `current` still holds
    // the accepted item (the fake's accept clears it).
    expect(emitter.emitTelemetryEvent.mock.invocationCallOrder[0]).toBeLessThan(
      originalAccept.mock.invocationCallOrder[0]
    );
  });

  it('reads the model info lazily at accept time, not at widget construction', () => {
    const completer = makeCompleter(NBI_INLINE_COMPLETION_PROVIDER_ID);
    const defaultFactory = { factory: jest.fn(() => completer) } as any;
    const emitter = { emitTelemetryEvent: jest.fn() };
    const getModelInfo = jest.fn(() => ({ provider: 'p', model: 'm' }));

    const wrapped = wrapInlineCompleterFactory(
      defaultFactory,
      emitter,
      getModelInfo
    );
    wrapped.factory({} as any);
    expect(getModelInfo).not.toHaveBeenCalled();

    completer.accept();
    expect(getModelInfo).toHaveBeenCalledTimes(1);
  });

  it('does not emit for another provider, but still calls the original accept', () => {
    const { completer, originalAccept, emitter } = setup('some-other-provider');

    completer.accept();

    expect(emitter.emitTelemetryEvent).not.toHaveBeenCalled();
    expect(originalAccept).toHaveBeenCalledTimes(1);
  });

  it('does not emit when there is no current item or provider, but still accepts', () => {
    for (const identifier of [undefined, null] as (undefined | null)[]) {
      const { completer, originalAccept, emitter } = setup(identifier);

      completer.accept();

      expect(emitter.emitTelemetryEvent).not.toHaveBeenCalled();
      expect(originalAccept).toHaveBeenCalledTimes(1);
    }
  });
});
