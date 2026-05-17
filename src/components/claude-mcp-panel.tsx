// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React, { useEffect, useRef, useState } from 'react';
import { Dialog, showDialog } from '@jupyterlab/apputils';
import {
  ClaudeMCPScope,
  ClaudeMCPTransport,
  IClaudeMCPAddInput,
  IClaudeMCPServer,
  NBIAPI
} from '../api';
import { FormDialog } from './form-dialog';
import {
  configToInput,
  parseKVLines,
  parseMcpJsonEntry
} from './claude-mcp-paste';

const SCOPES: ClaudeMCPScope[] = ['user', 'project', 'local'];
const TRANSPORTS: ClaudeMCPTransport[] = ['stdio', 'sse', 'http'];

const SCOPE_HINT: Record<ClaudeMCPScope, string> = {
  user: 'available in all your projects',
  project: 'shared via the project repo (.mcp.json)',
  local: 'this project, this user only'
};

export function SettingsPanelComponentClaudeMCP(_props: any): JSX.Element {
  const [servers, setServers] = useState<IClaudeMCPServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<IClaudeMCPServer | null>(
    null
  );

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await NBIAPI.listClaudeMCPServers();
      setServers(list);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleRemove = async (srv: IClaudeMCPServer) => {
    const ok = await showDialog({
      title: 'Remove MCP server?',
      body: `"${srv.name}" will be removed from Claude's ${srv.scope}-scope config.`,
      buttons: [Dialog.cancelButton(), Dialog.warnButton({ label: 'Remove' })]
    });
    if (!ok.button.accept) {
      return;
    }
    setPendingRemoval(srv);
    try {
      await NBIAPI.removeClaudeMCPServer(srv.name, srv.scope);
      await refresh();
    } catch (e: any) {
      setError(`Failed to remove: ${e?.message ?? e}`);
    } finally {
      setPendingRemoval(null);
    }
  };

  const handleAddSubmit = async (input: IClaudeMCPAddInput) => {
    // Errors are rendered inside the dialog so they're not hidden behind the
    // modal backdrop; rethrow so the dialog can keep itself open.
    await NBIAPI.addClaudeMCPServer(input);
    setAddOpen(false);
    await refresh();
  };

  const grouped: Record<ClaudeMCPScope, IClaudeMCPServer[]> = {
    user: [],
    project: [],
    local: []
  };
  for (const srv of servers) {
    (grouped[srv.scope as ClaudeMCPScope] ?? grouped.user).push(srv);
  }

  return (
    <div className="config-dialog-body nbi-skills-panel">
      <div className="nbi-skills-header">
        <div className="nbi-skills-title">Claude MCP</div>
        <div className="nbi-skills-header-actions">
          <button
            className="jp-Dialog-button jp-mod-reject jp-mod-styled"
            onClick={refresh}
            disabled={loading}
            title="Re-read Claude's MCP config from disk"
          >
            <div className="jp-Dialog-buttonLabel">
              {loading ? 'Refreshing…' : 'Refresh'}
            </div>
          </button>
          <button
            className="jp-Dialog-button jp-mod-reject jp-mod-styled"
            onClick={() => setAddOpen(true)}
          >
            <div className="jp-Dialog-buttonLabel">Add server</div>
          </button>
        </div>
      </div>

      <div className="nbi-info-banner" role="note">
        These are Claude Code's own MCP servers (read from{' '}
        <code>~/.claude.json</code>, project <code>.mcp.json</code>, and the
        per-user-per-project block). Independent of the NBI MCP Servers tab.
      </div>

      {error && (
        <div className="nbi-skills-error" role="alert">
          {error}
        </div>
      )}

      {SCOPES.map(scope => (
        <ClaudeMCPScopeSection
          key={scope}
          scope={scope}
          servers={grouped[scope]}
          loading={loading}
          pendingRemoval={pendingRemoval}
          onRemove={handleRemove}
        />
      ))}

      {addOpen && (
        <ClaudeMCPAddDialog
          onCancel={() => setAddOpen(false)}
          onSubmit={handleAddSubmit}
        />
      )}
    </div>
  );
}

function ClaudeMCPScopeSection(props: {
  scope: ClaudeMCPScope;
  servers: IClaudeMCPServer[];
  loading: boolean;
  pendingRemoval: IClaudeMCPServer | null;
  onRemove: (srv: IClaudeMCPServer) => void;
}) {
  return (
    <div className="nbi-skills-section">
      <div
        className="nbi-skills-section-caption"
        title={SCOPE_HINT[props.scope]}
      >
        {props.scope.toUpperCase()}
      </div>
      {props.servers.length === 0 ? (
        <div className="nbi-skills-empty">
          {props.loading ? 'Loading…' : 'No servers in this scope.'}
        </div>
      ) : (
        props.servers.map(srv => (
          <ClaudeMCPRow
            key={`${srv.scope}-${srv.name}`}
            srv={srv}
            removing={
              props.pendingRemoval?.name === srv.name &&
              props.pendingRemoval?.scope === srv.scope
            }
            onRemove={() => props.onRemove(srv)}
          />
        ))
      )}
    </div>
  );
}

function ClaudeMCPRow(props: {
  srv: IClaudeMCPServer;
  removing: boolean;
  onRemove: () => void;
}) {
  const { srv } = props;
  const summary =
    srv.transport === 'stdio'
      ? [srv.command, ...srv.args].filter(Boolean).join(' ')
      : srv.url;
  return (
    <div className="nbi-skill-row">
      <div className="nbi-skill-row-main">
        <div className="nbi-skill-row-name">{srv.name}</div>
        <div className="nbi-skill-row-description">
          <code>{srv.transport}</code>
          {summary && <span> — {summary}</span>}
        </div>
      </div>
      <div className="nbi-skill-row-actions" onClick={e => e.stopPropagation()}>
        <button
          className="jp-Dialog-button jp-mod-reject jp-mod-styled"
          onClick={props.onRemove}
          disabled={props.removing}
        >
          <div className="jp-Dialog-buttonLabel">
            {props.removing ? 'Removing…' : 'Remove'}
          </div>
        </button>
      </div>
    </div>
  );
}

type AddDialogMode = 'form' | 'json';

const JSON_PLACEHOLDER = `"server-key": {
  "command": "uvx",
  "args": ["server-package@latest"]
}`;

const FORM_TAB_ID = 'nbi-mcp-add-tab-form';
const JSON_TAB_ID = 'nbi-mcp-add-tab-json';
const FORM_PANEL_ID = 'nbi-mcp-add-panel-form';
const JSON_PANEL_ID = 'nbi-mcp-add-panel-json';

function ClaudeMCPAddDialog(props: {
  onCancel: () => void;
  onSubmit: (input: IClaudeMCPAddInput) => Promise<void>;
}) {
  const [scope, setScope] = useState<ClaudeMCPScope>('user');
  const [mode, setMode] = useState<AddDialogMode>('form');
  const [transport, setTransport] = useState<ClaudeMCPTransport>('stdio');
  const [name, setName] = useState('');
  const [commandOrUrl, setCommandOrUrl] = useState('');
  const [argsText, setArgsText] = useState('');
  const [envText, setEnvText] = useState('');
  const [headersText, setHeadersText] = useState('');
  const [jsonText, setJsonText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const nameInputRef = useRef<HTMLInputElement>(null);
  const jsonInputRef = useRef<HTMLTextAreaElement>(null);
  const formTabRef = useRef<HTMLButtonElement>(null);
  const jsonTabRef = useRef<HTMLButtonElement>(null);
  // Skip the first effect run so we don't steal focus from the Scope select
  // when the dialog mounts; only re-focus when the user actively switches.
  const hasMountedRef = useRef(false);

  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }
    if (mode === 'json') {
      jsonInputRef.current?.focus();
    } else {
      nameInputRef.current?.focus();
    }
  }, [mode]);

  const canSubmit =
    mode === 'json'
      ? jsonText.trim().length > 0 && !submitting
      : name.trim() && commandOrUrl.trim() && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) {
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      let input: IClaudeMCPAddInput;
      if (mode === 'json') {
        const { name: parsedName, config } = parseMcpJsonEntry(jsonText);
        input = configToInput(parsedName, config, scope);
      } else {
        const argsList = argsText
          .split('\n')
          .map(line => line.trim())
          .filter(Boolean);
        input = {
          name: name.trim(),
          scope,
          transport,
          commandOrUrl: commandOrUrl.trim(),
          args: transport === 'stdio' ? argsList : undefined,
          env: transport === 'stdio' ? parseKVLines(envText, '=') : undefined,
          headers:
            transport === 'stdio' ? undefined : parseKVLines(headersText, ':')
        };
      }
      await props.onSubmit(input);
    } catch (e: any) {
      setSubmitError(e?.message ?? String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const onTabsKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
      return;
    }
    event.preventDefault();
    const next: AddDialogMode = mode === 'form' ? 'json' : 'form';
    setMode(next);
    (next === 'form' ? formTabRef : jsonTabRef).current?.focus();
  };

  return (
    <FormDialog
      title="Add MCP server"
      submitLabel="Add"
      submitInProgressLabel="Adding…"
      canSubmit={Boolean(canSubmit)}
      submitting={submitting}
      error={submitError}
      onCancel={props.onCancel}
      onSubmit={handleSubmit}
    >
      <div className="nbi-form-field">
        <label>Scope</label>
        <select
          value={scope}
          onChange={e => setScope(e.target.value as ClaudeMCPScope)}
        >
          {SCOPES.map(s => (
            <option key={s} value={s}>
              {s} — {SCOPE_HINT[s]}
            </option>
          ))}
        </select>
      </div>
      <div className="nbi-form-field">
        <label id="nbi-mcp-add-input-mode-label">Input mode</label>
        <div
          className="nbi-segmented-control"
          role="tablist"
          aria-labelledby="nbi-mcp-add-input-mode-label"
          onKeyDown={onTabsKeyDown}
        >
          <button
            type="button"
            role="tab"
            id={FORM_TAB_ID}
            ref={formTabRef}
            aria-selected={mode === 'form'}
            aria-controls={FORM_PANEL_ID}
            tabIndex={mode === 'form' ? 0 : -1}
            className={`nbi-segmented-control-option${mode === 'form' ? ' is-active' : ''}`}
            onClick={() => setMode('form')}
          >
            Form
          </button>
          <button
            type="button"
            role="tab"
            id={JSON_TAB_ID}
            ref={jsonTabRef}
            aria-selected={mode === 'json'}
            aria-controls={JSON_PANEL_ID}
            tabIndex={mode === 'json' ? 0 : -1}
            className={`nbi-segmented-control-option${mode === 'json' ? ' is-active' : ''}`}
            onClick={() => setMode('json')}
          >
            JSON
          </button>
        </div>
      </div>
      {mode === 'json' ? (
        <div
          className="nbi-form-field"
          role="tabpanel"
          id={JSON_PANEL_ID}
          aria-labelledby={JSON_TAB_ID}
        >
          <label htmlFor="nbi-mcp-add-json">JSON</label>
          <textarea
            id="nbi-mcp-add-json"
            ref={jsonInputRef}
            rows={10}
            value={jsonText}
            onChange={e => setJsonText(e.target.value)}
            placeholder={JSON_PLACEHOLDER}
            spellCheck={false}
            autoFocus
          />
        </div>
      ) : (
        <div
          role="tabpanel"
          id={FORM_PANEL_ID}
          aria-labelledby={FORM_TAB_ID}
          className="nbi-mcp-add-form-panel"
        >
          <div className="nbi-form-field">
            <label htmlFor="nbi-mcp-add-name">Name</label>
            <input
              id="nbi-mcp-add-name"
              ref={nameInputRef}
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="my-server"
              autoFocus
            />
          </div>
          <div className="nbi-form-field">
            <label>Transport</label>
            <select
              value={transport}
              onChange={e => setTransport(e.target.value as ClaudeMCPTransport)}
            >
              {TRANSPORTS.map(t => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div className="nbi-form-field">
            <label>{transport === 'stdio' ? 'Command' : 'URL'}</label>
            <input
              type="text"
              value={commandOrUrl}
              onChange={e => setCommandOrUrl(e.target.value)}
              placeholder={
                transport === 'stdio' ? 'npx' : 'https://example.com/mcp'
              }
            />
          </div>
          {transport === 'stdio' && (
            <div className="nbi-form-field">
              <label>Args (one per line)</label>
              <textarea
                rows={3}
                value={argsText}
                onChange={e => setArgsText(e.target.value)}
                placeholder={'-y\n@scope/package@latest'}
              />
            </div>
          )}
          {transport === 'stdio' && (
            <div className="nbi-form-field">
              <label>Environment (KEY=value, one per line)</label>
              <textarea
                rows={3}
                value={envText}
                onChange={e => setEnvText(e.target.value)}
                placeholder="API_KEY=…"
              />
            </div>
          )}
          {transport !== 'stdio' && (
            <div className="nbi-form-field">
              <label>Headers (Name: value, one per line)</label>
              <textarea
                rows={3}
                value={headersText}
                onChange={e => setHeadersText(e.target.value)}
                placeholder="Authorization: Bearer …"
              />
            </div>
          )}
        </div>
      )}
    </FormDialog>
  );
}
