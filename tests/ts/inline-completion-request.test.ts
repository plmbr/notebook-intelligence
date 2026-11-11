// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import {
  classifyInlineCompletionResponse,
  IInlineCompletionRequestInfo,
  inlineCompletionText
} from '../../src/inline-completion-request';
import { BackendMessageType } from '../../src/tokens';

function makeRequest(messageId: string): IInlineCompletionRequestInfo {
  return {
    chatId: `chat-${messageId}`,
    messageId,
    requestTime: new Date('2026-01-01T00:00:00Z')
  };
}

describe('classifyInlineCompletionResponse', () => {
  it('accepts a completion for the request that is still current', () => {
    const request = makeRequest('a');

    expect(
      classifyInlineCompletionResponse('a', 'x = 1', request, request)
    ).toBe('accept');
  });

  it('ignores a response addressed to a different request', () => {
    const request = makeRequest('a');

    // Another callback owns this one. Resolving here would hand this
    // request's promise an answer computed for different text.
    expect(
      classifyInlineCompletionResponse('b', 'x = 1', request, request)
    ).toBe('ignore');
  });

  it('discards its own response once a newer request has started', () => {
    const request = makeRequest('a');
    const newer = makeRequest('b');

    // The regression this guards: reading the shared field instead of the
    // captured request made a slow answer look like it belonged to whichever
    // request had started most recently.
    expect(classifyInlineCompletionResponse('a', 'x = 1', request, newer)).toBe(
      'discard'
    );
  });

  it('accepts an empty completion, a response with nothing to suggest', () => {
    const request = makeRequest('a');

    expect(classifyInlineCompletionResponse('a', '', request, request)).toBe(
      'accept'
    );
  });

  it('discards a response with no completion text', () => {
    const request = makeRequest('a');

    expect(classifyInlineCompletionResponse('a', null, request, request)).toBe(
      'discard'
    );
  });

  it('ignores a foreign response even when superseded', () => {
    const request = makeRequest('a');
    const newer = makeRequest('b');

    // Ownership is checked first on purpose: a callback must never resolve a
    // promise for a message it was not waiting for, superseded or not.
    expect(classifyInlineCompletionResponse('c', 'x = 1', request, newer)).toBe(
      'ignore'
    );
  });

  it('discards when the provider has no request on record', () => {
    const request = makeRequest('a');

    expect(classifyInlineCompletionResponse('a', 'x = 1', request, null)).toBe(
      'discard'
    );
  });

  it('distinguishes requests by identity, not by equal field values', () => {
    const request = makeRequest('a');
    const lookalike = makeRequest('a');

    // Two requests can carry the same id only through a bug, but identity
    // comparison is what the provider relies on, so pin it.
    expect(
      classifyInlineCompletionResponse('a', 'x = 1', request, lookalike)
    ).toBe('discard');
  });
});

describe('inlineCompletionText', () => {
  it('reads the completion from a stream message', () => {
    expect(
      inlineCompletionText({
        type: BackendMessageType.StreamMessage,
        data: { completions: 'x = 1' }
      })
    ).toBe('x = 1');
  });

  it("has none in a failed request's error notice", () => {
    // What the server streams when the request fails: a chat-style notice,
    // with no completions field. Passed on, its undefined text made the
    // ghost text renderer throw and the drawn caret stop (#535).
    const notice = {
      type: BackendMessageType.StreamMessage,
      data: {
        choices: [
          {
            delta: {
              nbiContent: {
                type: 'markdown-part',
                content: 'Oops!',
                reasoning_content: null
              },
              content: '',
              role: 'assistant'
            }
          }
        ]
      }
    };
    expect(inlineCompletionText(notice)).toBeNull();
  });

  it('keeps an empty completion, which means no suggestion', () => {
    expect(
      inlineCompletionText({
        type: BackendMessageType.StreamMessage,
        data: { completions: '' }
      })
    ).toBe('');
  });

  it('has none in a stream end, a missing payload or a non-string one', () => {
    expect(
      inlineCompletionText({ type: BackendMessageType.StreamEnd, data: {} })
    ).toBeNull();
    expect(
      inlineCompletionText({
        type: BackendMessageType.StreamMessage,
        data: null
      })
    ).toBeNull();
    for (const completions of [null, 42, { text: 'x' }]) {
      expect(
        inlineCompletionText({
          type: BackendMessageType.StreamMessage,
          data: { completions }
        })
      ).toBeNull();
    }
  });
});
