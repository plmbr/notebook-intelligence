import { UUID } from '@lumino/coreutils';

import { IChatParticipant, ResponseStreamDataType } from './tokens';

export interface IHistoryWireMessage {
  role?: string;
  content?: string;
  reasoning_content?: string;
  tool_calls?: any[];
  ui_parts?: any[];
  participant_id?: string;
  created_at?: string;
}

function parseHistoryTimestamp(raw?: string): Date {
  if (!raw) {
    return new Date();
  }

  const trimmed = raw.trim();
  if (!trimmed) {
    return new Date();
  }

  // Persistent backends may return naive UTC strings like
  // "2026-06-11 14:53:58". Interpret those as UTC so refresh replay shows
  // the same local clock time as the live websocket event stream.
  const normalized =
    /(?:Z|[+-]\d{2}:\d{2})$/.test(trimmed) || trimmed.includes('T')
      ? trimmed
      : `${trimmed.replace(' ', 'T')}Z`;

  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

export interface IReplayChatMessageContent {
  id: string;
  type: ResponseStreamDataType;
  content: any;
  contentDetail?: any;
  created: Date;
  reasoningContent?: string;
  reasoningFinished?: boolean;
}

export interface IReplayChatMessage {
  id: string;
  date: Date;
  from: string;
  contents: IReplayChatMessageContent[];
  participant?: IChatParticipant;
}

function hasSerializedUiMessageParts(msg: IHistoryWireMessage): boolean {
  return Array.isArray(msg.ui_parts) && msg.ui_parts.length > 0;
}

function normalizeHistoryForReplay(
  history: IHistoryWireMessage[]
): IHistoryWireMessage[] {
  const normalized: IHistoryWireMessage[] = [];
  let turn: IHistoryWireMessage[] = [];

  const flushTurn = () => {
    if (turn.length === 0) {
      return;
    }

    const assistantUiMessages = turn.filter(
      msg =>
        (msg.role ?? 'assistant') === 'assistant' &&
        hasSerializedUiMessageParts(msg)
    );
    if (assistantUiMessages.length > 0) {
      const userMessage = turn.find(
        msg => (msg.role ?? 'assistant') === 'user'
      );
      if (userMessage) {
        normalized.push(userMessage);
      }
      normalized.push(assistantUiMessages[assistantUiMessages.length - 1]);
    } else {
      normalized.push(...turn);
    }

    turn = [];
  };

  for (const msg of history) {
    const role = msg.role ?? 'assistant';
    if (role === 'user' && turn.length > 0) {
      flushTurn();
    }
    turn.push(msg);
  }

  flushTurn();
  return normalized;
}

export function historyMessagesToChatMessages(
  history: IHistoryWireMessage[],
  participants: IChatParticipant[]
): IReplayChatMessage[] {
  const formattedMessages: IReplayChatMessage[] = [];

  for (const msg of normalizeHistoryForReplay(history)) {
    const role = msg.role ?? 'assistant';
    if (role === 'tool') {
      continue;
    }

    const date = parseHistoryTimestamp(msg.created_at);
    const hasMessageContent =
      !!msg.content ||
      !!msg.reasoning_content ||
      (Array.isArray(msg.ui_parts) && msg.ui_parts.length > 0);

    if (!hasMessageContent && role === 'assistant') {
      continue;
    }

    const serializedParts = Array.isArray(msg.ui_parts) ? msg.ui_parts : [];

    let contents: IReplayChatMessageContent[] = [];
    if (serializedParts.length > 0 && role === 'assistant') {
      contents = serializedParts.map((part: any) => ({
        id: UUID.uuid4(),
        type: ResponseStreamDataType.Markdown,
        content: part?.content || '',
        reasoningContent: part?.reasoning_content || '',
        reasoningFinished: !!part?.reasoning_content,
        contentDetail: part?.detail,
        created: date
      }));
    } else {
      contents = [
        {
          id: UUID.uuid4(),
          type: ResponseStreamDataType.Markdown,
          content: msg.content || '',
          reasoningContent: msg.reasoning_content,
          reasoningFinished: !!msg.reasoning_content,
          created: date
        }
      ];
    }

    if (role === 'user') {
      formattedMessages.push({
        id: UUID.uuid4(),
        date,
        from: 'user',
        contents
      });
      continue;
    }

    if (role === 'assistant') {
      formattedMessages.push({
        id: UUID.uuid4(),
        date,
        from: 'copilot',
        contents,
        participant: participants.find(p => p.id === msg.participant_id)
      });
    }
  }

  return formattedMessages;
}
