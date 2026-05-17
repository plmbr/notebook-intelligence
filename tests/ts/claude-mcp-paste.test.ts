/**
 * Tests for the JSON-paste branch of the "Add MCP server" dialog. The form
 * branch is exercised by the existing dialog state machine; this file covers
 * the parser that turns whatever the user pasted into an IClaudeMCPAddInput.
 *
 * Issue #278.
 */
import {
  parseMcpJsonEntry,
  configToInput
} from '../../src/components/claude-mcp-paste';

describe('parseMcpJsonEntry', () => {
  it('accepts a bare "key": {...} pair the user copied out of a config', () => {
    const raw =
      '"my-server": { "command": "uvx", "args": ["server-package@latest"] }';
    const { name, config } = parseMcpJsonEntry(raw);
    expect(name).toBe('my-server');
    expect(config.command).toBe('uvx');
    expect(config.args).toEqual(['server-package@latest']);
  });

  it('accepts a wrapped { "key": {...} } object', () => {
    const raw = '{ "my-server": { "command": "uvx" } }';
    const { name, config } = parseMcpJsonEntry(raw);
    expect(name).toBe('my-server');
    expect(config.command).toBe('uvx');
  });

  it('unwraps a full mcp.json with the mcpServers key', () => {
    const raw = `{
      "mcpServers": {
        "my-server": { "command": "uvx" }
      }
    }`;
    const { name } = parseMcpJsonEntry(raw);
    expect(name).toBe('my-server');
  });

  it('strips a stray leading comma (copy-from-larger-config artefact)', () => {
    const raw = ',"my-server": { "command": "uvx" }';
    const { name } = parseMcpJsonEntry(raw);
    expect(name).toBe('my-server');
  });

  it('strips a stray trailing comma too', () => {
    const raw = '"my-server": { "command": "uvx" },';
    const { name } = parseMcpJsonEntry(raw);
    expect(name).toBe('my-server');
  });

  it('rejects an mcpServers wrapper with no entries', () => {
    expect(() => parseMcpJsonEntry('{ "mcpServers": {} }')).toThrow(
      /at least one server/i
    );
  });

  it('rejects an mcpServers wrapper with multiple entries', () => {
    const raw =
      '{ "mcpServers": { "a": { "command": "x" }, "b": { "command": "y" } } }';
    expect(() => parseMcpJsonEntry(raw)).toThrow(/one entry at a time/i);
  });

  it('rejects empty input', () => {
    expect(() => parseMcpJsonEntry('')).toThrow(/empty/i);
    expect(() => parseMcpJsonEntry('   ')).toThrow(/empty/i);
  });

  it('rejects unparseable JSON', () => {
    expect(() => parseMcpJsonEntry('not json')).toThrow(/Invalid JSON/i);
  });

  it('rejects arrays and primitives', () => {
    expect(() => parseMcpJsonEntry('[1, 2]')).toThrow(/server entry/i);
    expect(() => parseMcpJsonEntry('"just a string"')).toThrow(/server entry/i);
  });

  it('rejects multi-server payloads with a guiding message', () => {
    const raw = '{ "a": { "command": "x" }, "b": { "command": "y" } }';
    expect(() => parseMcpJsonEntry(raw)).toThrow(/one entry at a time/i);
  });

  it('rejects an empty object', () => {
    expect(() => parseMcpJsonEntry('{}')).toThrow(/at least one server/i);
  });

  it('rejects when the server value is not an object', () => {
    expect(() => parseMcpJsonEntry('{"my-server": "uvx"}')).toThrow(
      /must be an object/i
    );
  });
});

describe('configToInput', () => {
  it('maps a stdio server config into IClaudeMCPAddInput', () => {
    const input = configToInput(
      'my-server',
      {
        command: 'uvx',
        args: ['server-package@latest'],
        env: { TOKEN: 'abc' }
      },
      'user'
    );
    expect(input).toEqual({
      name: 'my-server',
      scope: 'user',
      transport: 'stdio',
      commandOrUrl: 'uvx',
      args: ['server-package@latest'],
      env: { TOKEN: 'abc' },
      headers: undefined
    });
  });

  it('infers http transport from a url field', () => {
    const input = configToInput(
      'remote',
      {
        url: 'https://example.com/mcp',
        headers: { Authorization: 'Bearer x' }
      },
      'project'
    );
    expect(input.transport).toBe('http');
    expect(input.commandOrUrl).toBe('https://example.com/mcp');
    expect(input.headers).toEqual({ Authorization: 'Bearer x' });
    expect(input.args).toBeUndefined();
    expect(input.env).toBeUndefined();
  });

  it('respects an explicit transport: "sse" override on a url server', () => {
    const input = configToInput(
      'remote',
      { url: 'https://example.com/mcp', transport: 'sse' },
      'user'
    );
    expect(input.transport).toBe('sse');
  });

  it('rejects a config missing both command and url', () => {
    expect(() =>
      configToInput('broken', { args: ['x'] } as any, 'user')
    ).toThrow(/command.*or.*url/i);
  });

  it('stringifies non-string env / headers values', () => {
    const input = configToInput(
      'srv',
      { command: 'x', env: { PORT: 8080, FLAG: true } },
      'user'
    );
    expect(input.env).toEqual({ PORT: '8080', FLAG: 'true' });
  });

  it('rejects explicit transport: "http" on a stdio-only config', () => {
    expect(() =>
      configToInput('srv', { command: 'uvx', transport: 'http' } as any, 'user')
    ).toThrow(/url/i);
  });

  it('rejects explicit transport: "stdio" on a url-only config', () => {
    expect(() =>
      configToInput(
        'srv',
        { url: 'https://example.com', transport: 'stdio' } as any,
        'user'
      )
    ).toThrow(/command/i);
  });

  it('ignores an unrecognized transport string and falls back to the shape', () => {
    const input = configToInput(
      'srv',
      { url: 'https://example.com', transport: 'pigeon' } as any,
      'user'
    );
    expect(input.transport).toBe('http');
  });

  it('drops non-array args silently rather than crashing', () => {
    const input = configToInput(
      'srv',
      { command: 'uvx', args: 'not-an-array' } as any,
      'user'
    );
    expect(input.args).toBeUndefined();
  });

  it('returns empty env when env is a non-object', () => {
    const input = configToInput(
      'srv',
      { command: 'uvx', env: 'BAD' } as any,
      'user'
    );
    expect(input.env).toEqual({});
  });
});
