// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import { ClaudeMCPScope, ClaudeMCPTransport, IClaudeMCPAddInput } from '../api';

const VALID_TRANSPORTS: ReadonlyArray<ClaudeMCPTransport> = [
  'stdio',
  'sse',
  'http'
];

// Accept any of these paste shapes:
//   "server-key": { ... }                          (bare key + object)
//   { "server-key": { ... } }                      (wrapped, one entry)
//   { "mcpServers": { "server-key": { ... } } }    (full mcp.json)
export function parseMcpJsonEntry(raw: string): {
  name: string;
  config: Record<string, any>;
} {
  const trimmed = raw.trim().replace(/^,|,$/g, '');
  if (!trimmed) {
    throw new Error('JSON is empty.');
  }

  let parsed: any;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    try {
      parsed = JSON.parse(`{${trimmed}}`);
    } catch (e) {
      throw new Error(`Invalid JSON: ${(e as Error).message}`);
    }
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('JSON must describe a server entry.');
  }
  if (parsed.mcpServers && typeof parsed.mcpServers === 'object') {
    parsed = parsed.mcpServers;
  }

  const keys = Object.keys(parsed);
  if (keys.length === 0) {
    throw new Error('Expected at least one server entry.');
  }
  if (keys.length > 1) {
    throw new Error('Multiple servers found; paste one entry at a time.');
  }
  const name = keys[0];
  const config = parsed[name];
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error(`Server "${name}" config must be an object.`);
  }
  return { name, config };
}

export function configToInput(
  name: string,
  config: Record<string, any>,
  scope: ClaudeMCPScope
): IClaudeMCPAddInput {
  const url = typeof config.url === 'string' ? config.url.trim() : '';
  const command =
    typeof config.command === 'string' ? config.command.trim() : '';
  if (!url && !command) {
    throw new Error('Server config must include "command" or "url".');
  }

  const explicitTransport =
    typeof config.transport === 'string' &&
    (VALID_TRANSPORTS as ReadonlyArray<string>).includes(config.transport)
      ? (config.transport as ClaudeMCPTransport)
      : null;

  // If the user pasted an explicit `transport`, it must match the shape of
  // the rest of the config: `stdio` requires `command`, `sse`/`http` require
  // `url`. A mismatch is more likely a typo than intent, and silently
  // downgrading to whatever shape we see is the footgun reviewers flagged.
  if (explicitTransport === 'stdio' && !command) {
    throw new Error('transport: "stdio" requires a "command" field.');
  }
  if ((explicitTransport === 'http' || explicitTransport === 'sse') && !url) {
    throw new Error(
      `transport: "${explicitTransport}" requires a "url" field.`
    );
  }

  const transport: ClaudeMCPTransport =
    explicitTransport ?? (url ? 'http' : 'stdio');
  const commandOrUrl = transport === 'stdio' ? command : url;

  return {
    name,
    scope,
    transport,
    commandOrUrl,
    args:
      transport === 'stdio' && Array.isArray(config.args)
        ? config.args.map(String)
        : undefined,
    env: transport === 'stdio' ? toStringRecord(config.env) : undefined,
    headers: transport !== 'stdio' ? toStringRecord(config.headers) : undefined
  };
}

export function parseKVLines(
  text: string,
  separator: string
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    const idx = trimmed.indexOf(separator);
    if (idx > 0) {
      out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
    }
  }
  return out;
}

function toStringRecord(obj: any): Record<string, string> {
  const out: Record<string, string> = {};
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj)) {
      out[String(k)] = String(v);
    }
  }
  return out;
}
