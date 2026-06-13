export interface IHistoryConfigLike {
  mode?: string;
  backend?: string;
}

function normalizeForStableStringify(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(item => normalizeForStableStringify(item));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, normalizeForStableStringify(nested)])
    );
  }
  return value;
}

export function buildHistorySessionScopeSignature(
  historyConfig: IHistoryConfigLike | null | undefined,
  backendConfigs: Record<string, Record<string, unknown>> | null | undefined,
  userScope?: string | null
): string {
  const mode = historyConfig?.mode ?? 'local';
  if (mode !== 'persistent') {
    return JSON.stringify({ mode, userScope: userScope ?? '' });
  }

  const backend = historyConfig?.backend ?? '';
  const backendConfig = backendConfigs?.[backend] ?? {};
  return JSON.stringify(
    normalizeForStableStringify({
      mode,
      backend,
      backendConfig,
      userScope: userScope ?? ''
    })
  );
}

export function shouldStartNewHistorySession(
  previousScopeSignature: string,
  nextScopeSignature: string
): boolean {
  return previousScopeSignature !== nextScopeSignature;
}
