// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React, { useEffect, useState } from 'react';
import { Dialog, showDialog } from '@jupyterlab/apputils';
import {
  IPluginInfo,
  IPluginMarketplaceInfo,
  NBIAPI,
  PluginScope
} from '../api';
import { FormDialog } from './form-dialog';

const SCOPES: PluginScope[] = ['user', 'project', 'local'];
const SCOPE_HINT: Record<PluginScope, string> = {
  user: 'available in all your projects',
  project: 'shared via the project repo',
  local: 'this project, this user only'
};

export function SettingsPanelComponentPlugins(_props: any): JSX.Element {
  const [plugins, setPlugins] = useState<IPluginInfo[]>([]);
  const [marketplaces, setMarketplaces] = useState<IPluginMarketplaceInfo[]>(
    []
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [installOpen, setInstallOpen] = useState(false);
  const [marketplaceOpen, setMarketplaceOpen] = useState(false);
  // Composite key (`scope:name`) so a user-scope plugin and a project-scope
  // plugin sharing a name don't clobber each other's busy indicators.
  const [busyPluginKey, setBusyPluginKey] = useState<string | null>(null);
  const [busyMarketplace, setBusyMarketplace] = useState<string | null>(null);
  const [allowGithubImport, setAllowGithubImport] = useState(
    NBIAPI.config.allowGithubPluginImport
  );

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, m] = await Promise.all([
        NBIAPI.listPlugins(),
        NBIAPI.listPluginMarketplaces()
      ]);
      setPlugins(p);
      setMarketplaces(m);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const handler = () => {
      setAllowGithubImport(NBIAPI.config.allowGithubPluginImport);
    };
    NBIAPI.configChanged.connect(handler);
    return () => {
      NBIAPI.configChanged.disconnect(handler);
    };
  }, []);

  const handleUninstall = async (p: IPluginInfo) => {
    const name = String(p.name ?? p.id ?? '');
    const scope = (p.scope as PluginScope) ?? 'user';
    if (!name) {
      return;
    }
    const ok = await showDialog({
      title: 'Uninstall plugin?',
      body: `"${name}" will be removed from Claude's ${scope}-scope config.`,
      buttons: [
        Dialog.cancelButton(),
        Dialog.warnButton({ label: 'Uninstall' })
      ]
    });
    if (!ok.button.accept) {
      return;
    }
    const busyKey = `${scope}:${name}`;
    setBusyPluginKey(busyKey);
    try {
      await NBIAPI.uninstallPlugin(name, scope);
      await refresh();
    } catch (e: any) {
      setError(`Failed to uninstall: ${e?.message ?? e}`);
    } finally {
      setBusyPluginKey(null);
    }
  };

  const handleToggleEnabled = async (p: IPluginInfo) => {
    const name = String(p.name ?? p.id ?? '');
    const scope = (p.scope as PluginScope) ?? 'user';
    if (!name) {
      return;
    }
    const busyKey = `${scope}:${name}`;
    setBusyPluginKey(busyKey);
    try {
      await NBIAPI.setPluginEnabled(name, scope, !p.enabled);
      await refresh();
    } catch (e: any) {
      setError(`Failed to update: ${e?.message ?? e}`);
    } finally {
      setBusyPluginKey(null);
    }
  };

  const handleRemoveMarketplace = async (m: IPluginMarketplaceInfo) => {
    const name = String(m.name ?? '');
    if (!name) {
      return;
    }
    const ok = await showDialog({
      title: 'Remove marketplace?',
      body: `"${name}" will be removed from Claude's plugin marketplaces.`,
      buttons: [Dialog.cancelButton(), Dialog.warnButton({ label: 'Remove' })]
    });
    if (!ok.button.accept) {
      return;
    }
    setBusyMarketplace(name);
    try {
      await NBIAPI.removePluginMarketplace(name);
      await refresh();
    } catch (e: any) {
      setError(`Failed to remove: ${e?.message ?? e}`);
    } finally {
      setBusyMarketplace(null);
    }
  };

  const grouped: Record<PluginScope, IPluginInfo[]> = {
    user: [],
    project: [],
    local: []
  };
  for (const p of plugins) {
    const scope = (p.scope as PluginScope) ?? 'user';
    (grouped[scope] ?? grouped.user).push(p);
  }

  return (
    <div className="config-dialog-body nbi-skills-panel">
      <div className="nbi-skills-header">
        <div className="nbi-skills-title">Plugins</div>
        <div className="nbi-skills-header-actions">
          <button
            className="jp-Dialog-button jp-mod-reject jp-mod-styled"
            onClick={refresh}
            disabled={loading}
          >
            <div className="jp-Dialog-buttonLabel">
              {loading ? 'Refreshing…' : 'Refresh'}
            </div>
          </button>
          <button
            className="jp-Dialog-button jp-mod-reject jp-mod-styled"
            onClick={() => setMarketplaceOpen(true)}
          >
            <div className="jp-Dialog-buttonLabel">Add marketplace</div>
          </button>
          <button
            className="jp-Dialog-button jp-mod-accept jp-mod-styled"
            onClick={() => setInstallOpen(true)}
          >
            <div className="jp-Dialog-buttonLabel">Install plugin</div>
          </button>
        </div>
      </div>

      <div className="nbi-info-banner" role="note">
        Add a marketplace to discover plugins, then install one to extend Claude
        Code with new commands, agents, and tool integrations.
      </div>

      {error && (
        <div className="nbi-skills-error" role="alert">
          {error}
        </div>
      )}

      <div className="nbi-skills-section">
        <div className="nbi-skills-section-caption">MARKETPLACES</div>
        {marketplaces.length === 0 ? (
          <div className="nbi-skills-empty">
            {loading
              ? 'Loading…'
              : 'No marketplaces configured. Add one to discover plugins.'}
          </div>
        ) : (
          marketplaces.map((m, i) => (
            <MarketplaceRow
              key={String(m.name ?? m.source ?? i)}
              info={m}
              busy={busyMarketplace === String(m.name ?? '')}
              onRemove={() => handleRemoveMarketplace(m)}
            />
          ))
        )}
      </div>

      {SCOPES.map(scope => (
        <PluginScopeSection
          key={scope}
          scope={scope}
          plugins={grouped[scope]}
          loading={loading}
          busyPluginKey={busyPluginKey}
          onUninstall={handleUninstall}
          onToggle={handleToggleEnabled}
        />
      ))}

      {installOpen && (
        <PluginInstallDialog
          marketplaces={marketplaces}
          onCancel={() => setInstallOpen(false)}
          onSubmit={async ({ plugin, scope }) => {
            await NBIAPI.installPlugin(plugin, scope);
            setInstallOpen(false);
            await refresh();
          }}
        />
      )}

      {marketplaceOpen && (
        <MarketplaceAddDialog
          allowGithubImport={allowGithubImport}
          onCancel={() => setMarketplaceOpen(false)}
          onSubmit={async ({ source, scope }) => {
            await NBIAPI.addPluginMarketplace(source, scope);
            setMarketplaceOpen(false);
            await refresh();
          }}
        />
      )}
    </div>
  );
}

function PluginScopeSection(props: {
  scope: PluginScope;
  plugins: IPluginInfo[];
  loading: boolean;
  busyPluginKey: string | null;
  onUninstall: (p: IPluginInfo) => void;
  onToggle: (p: IPluginInfo) => void;
}) {
  return (
    <div className="nbi-skills-section">
      <div
        className="nbi-skills-section-caption"
        title={SCOPE_HINT[props.scope]}
      >
        {props.scope.toUpperCase()}
      </div>
      {props.plugins.length === 0 ? (
        <div className="nbi-skills-empty">
          {props.loading ? 'Loading…' : 'No plugins in this scope.'}
        </div>
      ) : (
        props.plugins.map(p => {
          const scope = (p.scope as PluginScope) ?? props.scope;
          const name = String(p.name ?? p.id ?? '');
          const rowKey = `${scope}:${name}`;
          return (
            <PluginRow
              key={rowKey}
              plugin={p}
              busy={props.busyPluginKey === rowKey}
              onUninstall={() => props.onUninstall(p)}
              onToggle={() => props.onToggle(p)}
            />
          );
        })
      )}
    </div>
  );
}

function PluginRow(props: {
  plugin: IPluginInfo;
  busy: boolean;
  onUninstall: () => void;
  onToggle: () => void;
}) {
  const { plugin } = props;
  const description = [plugin.version, plugin.marketplace, plugin.description]
    .filter(Boolean)
    .map(String)
    .join(' · ');
  const enabled = plugin.enabled !== false;
  return (
    <div className="nbi-skill-row">
      <div className="nbi-skill-row-main">
        <div className="nbi-skill-row-name">
          {String(plugin.name ?? plugin.id ?? '(unnamed)')}
          {!enabled && <span> — disabled</span>}
        </div>
        {description && (
          <div className="nbi-skill-row-description">{description}</div>
        )}
      </div>
      <div className="nbi-skill-row-actions" onClick={e => e.stopPropagation()}>
        <button
          className="jp-Dialog-button jp-mod-reject jp-mod-styled"
          onClick={props.onToggle}
          disabled={props.busy}
        >
          <div className="jp-Dialog-buttonLabel">
            {enabled ? 'Disable' : 'Enable'}
          </div>
        </button>
        <button
          className="jp-Dialog-button jp-mod-reject jp-mod-styled"
          onClick={props.onUninstall}
          disabled={props.busy}
        >
          <div className="jp-Dialog-buttonLabel">
            {props.busy ? 'Working…' : 'Uninstall'}
          </div>
        </button>
      </div>
    </div>
  );
}

function MarketplaceRow(props: {
  info: IPluginMarketplaceInfo;
  busy: boolean;
  onRemove: () => void;
}) {
  const { info } = props;
  return (
    <div className="nbi-skill-row">
      <div className="nbi-skill-row-main">
        <div className="nbi-skill-row-name">
          {String(info.name ?? '(unnamed)')}
        </div>
        {info.source && (
          <div className="nbi-skill-row-description">
            <code>{String(info.source)}</code>
          </div>
        )}
      </div>
      <div className="nbi-skill-row-actions" onClick={e => e.stopPropagation()}>
        <button
          className="jp-Dialog-button jp-mod-reject jp-mod-styled"
          onClick={props.onRemove}
          disabled={props.busy}
        >
          <div className="jp-Dialog-buttonLabel">
            {props.busy ? 'Removing…' : 'Remove'}
          </div>
        </button>
      </div>
    </div>
  );
}

function PluginInstallDialog(props: {
  marketplaces: IPluginMarketplaceInfo[];
  onCancel: () => void;
  onSubmit: (input: { plugin: string; scope: PluginScope }) => Promise<void>;
}) {
  const [pluginRef, setPluginRef] = useState('');
  const [scope, setScope] = useState<PluginScope>('user');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const canSubmit = pluginRef.trim() && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) {
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      await props.onSubmit({ plugin: pluginRef.trim(), scope });
    } catch (e: any) {
      setSubmitError(e?.message ?? String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <FormDialog
      title="Install plugin"
      submitLabel="Install"
      submitInProgressLabel="Installing…"
      canSubmit={Boolean(canSubmit)}
      submitting={submitting}
      error={submitError}
      onCancel={props.onCancel}
      onSubmit={handleSubmit}
    >
      <div className="nbi-form-field">
        <label>Plugin</label>
        <input
          type="text"
          value={pluginRef}
          onChange={e => setPluginRef(e.target.value)}
          placeholder="plugin-name or plugin@marketplace"
          autoFocus
        />
      </div>
      {props.marketplaces.length === 0 && (
        <div className="nbi-form-hint">
          No marketplaces are configured. Add one before installing, or specify{' '}
          <code>plugin@marketplace</code> with a known source.
        </div>
      )}
      <div className="nbi-form-field">
        <label>Scope</label>
        <select
          value={scope}
          onChange={e => setScope(e.target.value as PluginScope)}
        >
          {SCOPES.map(s => (
            <option key={s} value={s}>
              {s} — {SCOPE_HINT[s]}
            </option>
          ))}
        </select>
      </div>
    </FormDialog>
  );
}

function MarketplaceAddDialog(props: {
  allowGithubImport: boolean;
  onCancel: () => void;
  onSubmit: (input: { source: string; scope: PluginScope }) => Promise<void>;
}) {
  const [source, setSource] = useState('');
  const [scope, setScope] = useState<PluginScope>('user');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const canSubmit = source.trim() && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) {
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      await props.onSubmit({ source: source.trim(), scope });
    } catch (e: any) {
      setSubmitError(e?.message ?? String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <FormDialog
      title="Add plugin marketplace"
      submitLabel="Add"
      submitInProgressLabel="Adding…"
      canSubmit={Boolean(canSubmit)}
      submitting={submitting}
      error={submitError}
      onCancel={props.onCancel}
      onSubmit={handleSubmit}
    >
      <div className="nbi-form-field">
        <label>Source</label>
        <input
          type="text"
          value={source}
          onChange={e => setSource(e.target.value)}
          placeholder={
            props.allowGithubImport
              ? 'owner/repo, https://github.com/owner/repo, or local path'
              : 'https://… or local path'
          }
          autoFocus
        />
      </div>
      {props.allowGithubImport ? (
        <div className="nbi-form-hint">
          Private GitHub sources work if <code>GITHUB_TOKEN</code> is set or{' '}
          <code>gh auth login</code> is configured on the Jupyter server.
        </div>
      ) : (
        <div className="nbi-form-hint">
          GitHub-sourced marketplaces are disabled by your administrator. Use a
          non-GitHub URL or a local filesystem path.
        </div>
      )}
      <div className="nbi-form-field">
        <label>Scope</label>
        <select
          value={scope}
          onChange={e => setScope(e.target.value as PluginScope)}
        >
          {SCOPES.map(s => (
            <option key={s} value={s}>
              {s} — {SCOPE_HINT[s]}
            </option>
          ))}
        </select>
      </div>
    </FormDialog>
  );
}
