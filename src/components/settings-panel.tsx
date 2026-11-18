// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React, { useEffect, useRef, useState } from 'react';
import { ReactWidget } from '@jupyterlab/apputils';
import { ISignal, Signal } from '@lumino/signaling';
import { VscTriangleDown, VscTriangleRight, VscWarning } from '../icons';
import * as path from 'path';

import copySvgstr from '../../style/icons/copy.svg';
import claudeSvgStr from '../../style/icons/claude.svg';
import openaiSvgStr from '../../style/icons/openai.svg';
import {
  ClaudeModelType,
  ClaudeToolType,
  ICellOutputFeatureFlag,
  IClaudeModelInfo,
  NBIAPI
} from '../api';
import { TranslationBundle } from '@jupyterlab/translation';
import { getTextDirection, interpolate, useTrans } from '../i18n';
import {
  lockedByEnvironmentTip,
  lockedTip,
  optionalLabel
} from './setting-lock';
import { CheckBoxItem } from './checkbox';
import { ReadinessCard } from './readiness-card';
import { PillItem } from './pill';
import {
  mcpServerSettingsToEnabledState,
  mcpServerStatusTitle
} from './mcp-util';
import { SettingsPanelComponentSkills } from './skills-panel';
import { SettingsPanelComponentClaudeMCP } from './claude-mcp-panel';
import { SettingsPanelComponentPlugins } from './plugins-panel';
import { SettingsPanelComponentPerf } from './perf-panel';
import { writeTextToClipboard } from '../utils';
import {
  CHATBOOK_EXECUTION_MODES,
  clampChatbookExecutionMode,
  type ChatbookExecutionMode
} from '../chatbook-core';
import {
  listChatbookBackendProfiles,
  resolveChatbookBackendProfile,
  sharedKernelSpecManager,
  type INotebookKernelProfile
} from '../notebook-kernels';

// Stable id helper so the tab and its panel agree on aria-controls /
// aria-labelledby without scattering string concatenation through the
// component.
const tabId = (prefix: string, id: string): string => `${prefix}-${id}`;

type TablistOrientation = 'vertical' | 'horizontal';

// WAI-ARIA tablist arrow-key navigation. Same shape for both the
// vertical (Up/Down) main tabs and the horizontal (Left/Right) Claude
// subtabs — the orientation flag picks which keys move the cursor.
// Returns an ``onKeyDown`` for the tablist container; callers decide
// what to do with each id (typically: select + focus).
function useTablistArrowKeys<T extends { id: string }>(
  tabs: T[],
  activeId: string,
  onSelect: (id: string) => void,
  orientation: TablistOrientation,
  domIdFor: (id: string) => string
): (e: React.KeyboardEvent<HTMLDivElement>) => void {
  return (e: React.KeyboardEvent<HTMLDivElement>) => {
    const key = e.key;
    const prevKey = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';
    const nextKey = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
    if (key !== prevKey && key !== nextKey && key !== 'Home' && key !== 'End') {
      return;
    }
    e.preventDefault();
    const idx = tabs.findIndex(t => t.id === activeId);
    let next = idx;
    if (key === nextKey) {
      next = (idx + 1) % tabs.length;
    } else if (key === prevKey) {
      next = (idx - 1 + tabs.length) % tabs.length;
    } else if (key === 'Home') {
      next = 0;
    } else if (key === 'End') {
      next = tabs.length - 1;
    }
    onSelect(tabs[next].id);
    document.getElementById(domIdFor(tabs[next].id))?.focus();
  };
}

// When a boolean policy is locked the panel shows the policy-resolved value;
// otherwise it shows the user's local toggle state.
const checkedValue = (
  policy: ICellOutputFeatureFlag,
  userValue: boolean
): boolean => (policy.locked ? policy.enabled : userValue);

function useNbiPolicies() {
  const [featurePolicies, setFeaturePolicies] = useState(
    NBIAPI.config.featurePolicies
  );
  const [settingLocks, setSettingLocks] = useState(NBIAPI.config.settingLocks);
  useEffect(() => {
    const handler = () => {
      setFeaturePolicies(NBIAPI.config.featurePolicies);
      setSettingLocks(NBIAPI.config.settingLocks);
    };
    NBIAPI.configChanged.connect(handler);
    return () => {
      NBIAPI.configChanged.disconnect(handler);
    };
  }, []);
  return { featurePolicies, settingLocks };
}

const OPENAI_COMPATIBLE_CHAT_MODEL_ID = 'openai-compatible-chat-model';

/**
 * What the server sends in place of a stored API key (see
 * credential_mask.py). Posting it back leaves the stored key as it is.
 */
const SECRET_MASK = '********';

/**
 * Select the mask when a key field gains focus, so the first keystroke or
 * paste replaces it. Without this, typing appends to the mask and saves
 * `********abc` as the key.
 */
function selectMask(event: React.FocusEvent<HTMLInputElement>): void {
  if (event.target.value === SECRET_MASK) {
    event.target.select();
  }
}

/**
 * A required provider property left empty. The value persists as an empty
 * string and requests then go out with that field blank, which the endpoint
 * rejects, so the field has to say so rather than looking saved.
 */
export function isBlankRequiredProperty(property: {
  optional?: boolean;
  value?: string;
}): boolean {
  return !property.optional && !(property.value || '').trim();
}

/**
 * One provider property input. The required-field error waits for the user to
 * touch the field: these start empty whenever a provider is first selected,
 * and painting errors on fields nobody has typed in yet reads as broken
 * rather than as guidance.
 */
/**
 * The provider property inputs for one model.
 *
 * Keyed by provider, model and property id rather than by position: the
 * providers order their properties differently, so a positional key would
 * carry one field's state onto whatever field lands in that slot next.
 */
export function ModelPropertyList(props: {
  properties: {
    id: string;
    name: string;
    description: string;
    value: string;
    optional?: boolean;
    secret?: boolean;
  }[];
  providerId: string;
  modelId: string;
  inputName: string;
  onPropertyChange: (propertyId: string, value: string) => void;
}): JSX.Element {
  return (
    <>
      {props.properties.map(property => (
        <ModelPropertyField
          key={`${props.providerId}:${props.modelId}:${property.id}`}
          property={property}
          inputName={props.inputName}
          onChange={value => props.onPropertyChange(property.id, value)}
        />
      ))}
    </>
  );
}

/**
 * What config.json keeps of a model's settings: the server reads back only
 * id and value, and the labels arrive in the user's language, which a saved
 * file should not record.
 */
function savedProperties(
  properties: { id: string; value: string }[]
): { id: string; value: string }[] {
  return properties.map(({ id, value }) => ({ id, value }));
}

export function ModelPropertyField(props: {
  property: {
    id: string;
    name: string;
    description: string;
    value: string;
    optional?: boolean;
    secret?: boolean;
  };
  inputName: string;
  onChange: (value: string) => void;
}): JSX.Element {
  const trans = useTrans();
  const { property, inputName, onChange } = props;
  const [touched, setTouched] = useState(false);
  const showError = touched && isBlankRequiredProperty(property);
  return (
    <div className="form-field-row">
      <div className="form-field-description">
        {property.optional
          ? optionalLabel(trans, property.name)
          : property.name}
      </div>
      <input
        name={inputName}
        type={property.secret ? 'password' : 'text'}
        autoComplete={property.secret ? 'new-password' : undefined}
        placeholder={property.description}
        className="jp-mod-styled"
        spellCheck={false}
        value={property.value}
        aria-invalid={showError ? true : undefined}
        onChange={event => {
          setTouched(true);
          onChange(event.target.value);
        }}
        onFocus={property.secret ? selectMask : undefined}
        onBlur={() => setTouched(true)}
      />
      {showError && (
        <div className="nbi-form-field-error">
          {trans.__('%1 is required.', property.name)}
        </div>
      )}
    </div>
  );
}
const LITELLM_COMPATIBLE_CHAT_MODEL_ID = 'litellm-compatible-chat-model';
const OPENAI_COMPATIBLE_INLINE_COMPLETION_MODEL_ID =
  'openai-compatible-inline-completion-model';
const LITELLM_COMPATIBLE_INLINE_COMPLETION_MODEL_ID =
  'litellm-compatible-inline-completion-model';

export class SettingsPanel extends ReactWidget {
  constructor(options: {
    onSave: () => void;
    onEditMCPConfigClicked: () => void;
    initialTab?: string;
  }) {
    super();

    this._onSave = options.onSave;
    this._onEditMCPConfigClicked = options.onEditMCPConfigClicked;
    this._activeTab = options.initialTab ?? 'general';
  }

  /**
   * Deep link into a section. The signal covers a panel that is already
   * mounted; `_activeTab` covers one that mounts right after this call.
   */
  selectTab(tab: string): void {
    this._activeTab = tab;
    this._tabRequested.emit(tab);
  }

  render(): JSX.Element {
    return (
      <SettingsPanelComponent
        onSave={this._onSave}
        onEditMCPConfigClicked={this._onEditMCPConfigClicked}
        initialTab={this._activeTab}
        tabRequested={this._tabRequested}
      />
    );
  }

  private _onSave: () => void;
  private _onEditMCPConfigClicked: () => void;
  private _activeTab: string;
  private _tabRequested = new Signal<this, string>(this);
}

// Tab declaration. Adding a new tab is one entry here plus an icon
// (optional). The `visible` predicate runs against {featurePolicies,
// isInClaudeCodeMode, isClaudeCliAvailable} so policy / mode changes
// propagate through the registry without wiring extra props.
type TabSpec = {
  id: string;
  // A function, so the label is translated when the panel renders rather
  // than when this module loads.
  label: (trans: TranslationBundle) => string;
  icon?: () => JSX.Element;
  visible: (ctx: TabVisibilityContext) => boolean;
  render: (props: any) => JSX.Element;
};
type TabVisibilityContext = {
  featurePolicies: import('../api').IFeaturePolicies;
  isInClaudeCodeMode: boolean;
  isClaudeCliAvailable: boolean;
  chatbookEnabled: boolean;
};

export const SETTINGS_TABS: TabSpec[] = [
  {
    id: 'general',
    label: trans => trans._p('settings tab', 'General'),
    visible: () => true,
    render: props => (
      <SettingsPanelComponentGeneral
        onSave={props.onSave}
        onEditMCPConfigClicked={props.onEditMCPConfigClicked}
      />
    )
  },
  {
    id: 'chatbook',
    label: trans => trans._p('settings tab', 'Chatbook'),
    visible: ctx => ctx.chatbookEnabled,
    render: () => <SettingsPanelComponentChatbook />
  },
  {
    id: 'claude',
    // Product names are not translated.
    label: () => 'Claude',
    icon: () => (
      <span
        className="claude-icon"
        dangerouslySetInnerHTML={{ __html: claudeSvgStr }}
      ></span>
    ),
    visible: () => true,
    render: props => (
      <SettingsPanelComponentClaude
        onEditMCPConfigClicked={props.onEditMCPConfigClicked}
      />
    )
  },
  {
    id: 'acp',
    label: () => 'ACP',
    icon: () => (
      <span
        className="acp-agent-icon"
        dangerouslySetInnerHTML={{ __html: openaiSvgStr }}
      ></span>
    ),
    // Hidden unless an admin has unlocked the experimental ACP mode
    // (acp_mode defaults to force-off, which reads as locked + disabled).
    visible: ctx =>
      ctx.featurePolicies.acp_mode.enabled ||
      !ctx.featurePolicies.acp_mode.locked,
    render: () => <SettingsPanelComponentAcp />
  },
  {
    id: 'mcp-servers',
    label: trans => trans._p('settings tab', 'MCP Servers'),
    visible: ctx => !ctx.isInClaudeCodeMode,
    render: props => (
      <SettingsPanelComponentMCPServers
        onEditMCPConfigClicked={props.onEditMCPConfigClicked}
      />
    )
  },
  {
    id: 'claude-mcp',
    label: () => 'Claude MCP',
    visible: ctx =>
      ctx.featurePolicies.claude_mcp_management.enabled &&
      ctx.isInClaudeCodeMode &&
      ctx.isClaudeCliAvailable,
    render: () => <SettingsPanelComponentClaudeMCP />
  },
  {
    id: 'plugins',
    label: trans => trans._p('settings tab', 'Plugins'),
    visible: ctx =>
      ctx.featurePolicies.claude_plugins_management.enabled &&
      ctx.isInClaudeCodeMode &&
      ctx.isClaudeCliAvailable,
    render: () => <SettingsPanelComponentPlugins />
  },
  {
    id: 'skills',
    label: trans => trans._p('settings tab', 'Skills'),
    visible: ctx => ctx.featurePolicies.skills_management.enabled,
    render: () => <SettingsPanelComponentSkills />
  },
  {
    id: 'perf',
    label: trans => trans._p('settings tab', 'Performance'),
    // Not gated on `enabled`, which is the user's own toggle and is off by
    // default: gating on it would hide the tab that contains the toggle.
    // Hidden only under force-off, where both perf endpoints 404 and there
    // is nothing on the tab a user can do.
    visible: ctx => {
      const policy = ctx.featurePolicies.perf_diagnostics;
      return !(policy?.locked === true && policy?.enabled === false);
    },
    render: () => <SettingsPanelComponentPerf />
  }
];

function SettingsPanelComponent(props: any) {
  const [activeTab, setActiveTab] = useState(props.initialTab || 'general');
  const { featurePolicies } = useNbiPolicies();
  const [isInClaudeCodeMode, setIsInClaudeCodeMode] = useState(
    NBIAPI.config.isInClaudeCodeMode
  );
  const [isClaudeCliAvailable, setIsClaudeCliAvailable] = useState(
    NBIAPI.config.isClaudeCliAvailable
  );
  const [chatbookEnabled, setChatbookEnabled] = useState(
    NBIAPI.config.chatbookEnabled
  );

  useEffect(() => {
    const handler = () => {
      setIsInClaudeCodeMode(NBIAPI.config.isInClaudeCodeMode);
      setIsClaudeCliAvailable(NBIAPI.config.isClaudeCliAvailable);
      setChatbookEnabled(NBIAPI.config.chatbookEnabled);
    };
    NBIAPI.configChanged.connect(handler);
    return () => {
      NBIAPI.configChanged.disconnect(handler);
    };
  }, []);

  useEffect(() => {
    const requested: ISignal<unknown, string> | undefined = props.tabRequested;
    if (!requested) {
      return;
    }
    const handler = (_sender: unknown, tab: string) => {
      setActiveTab(tab);
    };
    requested.connect(handler);
    return () => {
      requested.disconnect(handler);
    };
  }, [props.tabRequested]);

  const ctx: TabVisibilityContext = {
    featurePolicies,
    isInClaudeCodeMode,
    isClaudeCliAvailable,
    chatbookEnabled
  };
  const visibleTabs = SETTINGS_TABS.filter(t => t.visible(ctx));
  const activeTabSpec = visibleTabs.find(t => t.id === activeTab);

  // Bounce off a tab that just disappeared (admin policy flip, mode toggle).
  useEffect(() => {
    if (!activeTabSpec) {
      setActiveTab('general');
    }
  }, [activeTabSpec]);

  return (
    <div className="nbi-settings-panel" dir={getTextDirection()}>
      <SettingsPanelTabsComponent
        tabs={visibleTabs}
        activeTab={activeTab}
        onTabSelected={setActiveTab}
      />
      <div
        className="nbi-settings-panel-tab-content"
        role="tabpanel"
        id={tabId('nbi-settings-tabpanel', activeTab)}
        aria-labelledby={tabId('nbi-settings-tab', activeTab)}
      >
        {activeTabSpec && activeTabSpec.render(props)}
      </div>
    </div>
  );
}

export function SettingsPanelTabsComponent(props: {
  tabs: TabSpec[];
  activeTab: string;
  onTabSelected: (tab: string) => void;
}) {
  const trans = useTrans();
  const onKeyDown = useTablistArrowKeys(
    props.tabs,
    props.activeTab,
    props.onTabSelected,
    'vertical',
    id => tabId('nbi-settings-tab', id)
  );

  return (
    <div
      className="nbi-settings-panel-tabs"
      role="tablist"
      aria-orientation="vertical"
      aria-label={trans.__('Settings sections')}
      onKeyDown={onKeyDown}
    >
      {props.tabs.map(tab => {
        const selected = tab.id === props.activeTab;
        return (
          <button
            type="button"
            key={tab.id}
            id={tabId('nbi-settings-tab', tab.id)}
            className={`nbi-settings-panel-tab ${selected ? 'active' : ''}`}
            role="tab"
            aria-selected={selected}
            aria-controls={tabId('nbi-settings-tabpanel', tab.id)}
            tabIndex={selected ? 0 : -1}
            onClick={() => props.onTabSelected(tab.id)}
          >
            {tab.icon && (
              // The icon is decoration: the label beside it is the name. Left
              // exposed, the svg is an unnamed image node inside the tab,
              // which some screen readers voice as "image", and accessible
              // name computations disagree about whether it suppresses the
              // name entirely. Hiding it settles both.
              <span aria-hidden="true">{tab.icon()}</span>
            )}
            {tab.label(trans)}
          </button>
        );
      })}
    </div>
  );
}

function SettingsPanelComponentGeneral(props: any) {
  const trans = useTrans();
  const nbiConfig = NBIAPI.config;
  const llmProviders = nbiConfig.llmProviders;
  const [chatModels, setChatModels] = useState([]);
  const [inlineCompletionModels, setInlineCompletionModels] = useState([]);
  const isInClaudeCodeMode = nbiConfig.isInClaudeCodeMode;

  const handleSaveSettings = async () => {
    const config: any = {
      default_chat_mode: defaultChatMode,
      chat_model: {
        provider: chatModelProvider,
        model: chatModel,
        properties: savedProperties(chatModelProperties)
      },
      inline_completion_model: {
        provider: inlineCompletionModelProvider,
        model: inlineCompletionModel,
        properties: savedProperties(inlineCompletionModelProperties)
      },
      inline_completion_debouncer_delay: inlineCompletionDebouncerDelay
    };

    if (
      chatModelProvider === 'github-copilot' ||
      inlineCompletionModelProvider === 'github-copilot'
    ) {
      config.store_github_access_token = storeGitHubAccessToken;
    }

    await NBIAPI.setConfig(config);

    props.onSave();
  };

  const handleRefreshOllamaModelListClick = async () => {
    await NBIAPI.updateOllamaModelList();
    updateModelOptionsForProvider(chatModelProvider, 'chat');
  };

  const [chatModelProvider, setChatModelProvider] = useState(
    nbiConfig.chatModel.provider || 'none'
  );
  const [inlineCompletionModelProvider, setInlineCompletionModelProvider] =
    useState(nbiConfig.inlineCompletionModel.provider || 'none');
  const [defaultChatMode, setDefaultChatMode] = useState<string>(
    nbiConfig.defaultChatMode
  );
  const [chatModel, setChatModel] = useState<string>(nbiConfig.chatModel.model);
  const [chatModelProperties, setChatModelProperties] = useState<any[]>([]);
  const [inlineCompletionModelProperties, setInlineCompletionModelProperties] =
    useState<any[]>([]);
  const [inlineCompletionModel, setInlineCompletionModel] = useState(
    nbiConfig.inlineCompletionModel.model
  );
  const [storeGitHubAccessToken, setStoreGitHubAccessToken] = useState(
    nbiConfig.storeGitHubAccessToken
  );
  const [inlineCompletionDebouncerDelay, setInlineCompletionDebouncerDelay] =
    useState(nbiConfig.inlineCompletionDebouncerDelay);
  const { featurePolicies, settingLocks } = useNbiPolicies();

  const toggleExplainError = () => {
    NBIAPI.setConfig({
      enable_explain_error: !featurePolicies.explain_error.enabled
    });
  };

  const toggleOutputFollowup = () => {
    NBIAPI.setConfig({
      enable_output_followup: !featurePolicies.output_followup.enabled
    });
  };

  const toggleOutputToolbar = () => {
    NBIAPI.setConfig({
      enable_output_toolbar: !featurePolicies.output_toolbar.enabled
    });
  };

  // Like the other toggles here, the box follows the saved config (through
  // configChanged) rather than flipping before the server has it.
  const toggleReplyInUserLanguage = () => {
    NBIAPI.setConfig({
      reply_in_user_language: !NBIAPI.config.replyInUserLanguage
    });
  };

  const toggleRefreshOpenFilesOnDiskChange = () => {
    NBIAPI.setConfig({
      refresh_open_files_on_disk_change:
        !featurePolicies.refresh_open_files_on_disk_change.enabled
    });
  };

  const updateModelOptionsForProvider = (
    providerId: string,
    modelType: 'chat' | 'inline-completion'
  ) => {
    if (modelType === 'chat') {
      setChatModelProvider(providerId);
    } else {
      setInlineCompletionModelProvider(providerId);
    }
    const models =
      modelType === 'chat'
        ? nbiConfig.chatModels
        : nbiConfig.inlineCompletionModels;
    const selectedModelId =
      modelType === 'chat'
        ? nbiConfig.chatModel.model
        : nbiConfig.inlineCompletionModel.model;

    const providerModels = models.filter(
      (model: any) => model.provider === providerId
    );
    if (modelType === 'chat') {
      setChatModels(providerModels);
    } else {
      setInlineCompletionModels(providerModels);
    }
    let selectedModel = providerModels.find(
      (model: any) => model.id === selectedModelId
    );
    if (!selectedModel) {
      selectedModel = providerModels?.[0];
    }
    if (selectedModel) {
      if (modelType === 'chat') {
        setChatModel(selectedModel.id);
        setChatModelProperties(selectedModel.properties);
      } else {
        setInlineCompletionModel(selectedModel.id);
        setInlineCompletionModelProperties(selectedModel.properties);
      }
    } else {
      if (modelType === 'chat') {
        setChatModelProperties([]);
      } else {
        setInlineCompletionModelProperties([]);
      }
    }
  };

  const onModelPropertyChange = (
    modelType: 'chat' | 'inline-completion',
    propertyId: string,
    value: string
  ) => {
    const modelProperties =
      modelType === 'chat'
        ? chatModelProperties
        : inlineCompletionModelProperties;
    const updatedProperties = modelProperties.map((property: any) => {
      if (property.id === propertyId) {
        return { ...property, value };
      }
      return property;
    });
    if (modelType === 'chat') {
      setChatModelProperties(updatedProperties);
    } else {
      setInlineCompletionModelProperties(updatedProperties);
    }
  };

  useEffect(() => {
    updateModelOptionsForProvider(chatModelProvider, 'chat');
    updateModelOptionsForProvider(
      inlineCompletionModelProvider,
      'inline-completion'
    );
  }, []);

  useEffect(() => {
    handleSaveSettings();
  }, [
    defaultChatMode,
    chatModelProvider,
    chatModel,
    chatModelProperties,
    inlineCompletionModelProvider,
    inlineCompletionModel,
    inlineCompletionModelProperties,
    storeGitHubAccessToken,
    inlineCompletionDebouncerDelay
  ]);

  return (
    <div className="config-dialog">
      <div className="config-dialog-body">
        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Status')}
          </div>
          <div className="model-config-section-body">
            <ReadinessCard />
          </div>
        </div>
        {!isInClaudeCodeMode && (
          <div className="model-config-section">
            <div className="model-config-section-header">
              {trans.__('Default chat mode')}
            </div>
            <div className="model-config-section-body">
              <div className="model-config-section-row">
                <div className="model-config-section-column">
                  <div>
                    <select
                      className="jp-mod-styled"
                      value={defaultChatMode}
                      onChange={event => setDefaultChatMode(event.target.value)}
                    >
                      <option value="ask">
                        {trans._p('chat mode', 'Ask')}
                      </option>
                      <option value="agent">
                        {trans._p('chat mode', 'Agent')}
                      </option>
                    </select>
                  </div>
                </div>
                <div className="model-config-section-column"> </div>
              </div>
            </div>
          </div>
        )}

        {!isInClaudeCodeMode && (
          <div className="model-config-section">
            <div className="model-config-section-header">
              {trans.__('Chat model')}
            </div>
            <div className="model-config-section-body">
              <div className="model-config-section-row">
                <div className="model-config-section-column">
                  <div>{trans.__('Provider')}</div>
                  <div
                    title={lockedTip(
                      trans,
                      settingLocks.chat_model_provider.locked
                    )}
                  >
                    <select
                      className="jp-mod-styled"
                      disabled={settingLocks.chat_model_provider.locked}
                      onChange={event =>
                        updateModelOptionsForProvider(
                          event.target.value,
                          'chat'
                        )
                      }
                    >
                      {llmProviders.map((provider: any, index: number) => (
                        <option
                          key={index}
                          value={provider.id}
                          selected={provider.id === chatModelProvider}
                        >
                          {provider.name}
                        </option>
                      ))}
                      <option
                        key={-1}
                        value="none"
                        selected={
                          chatModelProvider === 'none' ||
                          !llmProviders.find(
                            provider => provider.id === chatModelProvider
                          )
                        }
                      >
                        {trans._p('model provider', 'None')}
                      </option>
                    </select>
                  </div>
                </div>
                {!['openai-compatible', 'litellm-compatible', 'none'].includes(
                  chatModelProvider
                ) &&
                  chatModels.length > 0 && (
                    <div className="model-config-section-column">
                      <div>{trans.__('Model')}</div>
                      {![
                        OPENAI_COMPATIBLE_CHAT_MODEL_ID,
                        LITELLM_COMPATIBLE_CHAT_MODEL_ID
                      ].includes(chatModel) &&
                        chatModels.length > 0 && (
                          <div
                            title={lockedTip(
                              trans,
                              settingLocks.chat_model_id.locked
                            )}
                          >
                            <select
                              className="jp-mod-styled"
                              disabled={settingLocks.chat_model_id.locked}
                              onChange={event =>
                                setChatModel(event.target.value)
                              }
                            >
                              {chatModels.map((model: any, index: number) => (
                                <option
                                  key={index}
                                  value={model.id}
                                  selected={model.id === chatModel}
                                >
                                  {model.name}
                                </option>
                              ))}
                            </select>
                          </div>
                        )}
                    </div>
                  )}
              </div>

              <div className="model-config-section-row">
                <div className="model-config-section-column">
                  {chatModelProvider === 'ollama' &&
                    chatModels.length === 0 && (
                      <div className="ollama-warning-message">
                        {interpolate(
                          (ollama, tryAgain) =>
                            trans.__(
                              'No Ollama models found! Make sure %1 is running and models are downloaded to your computer. %2 once ready.',
                              ollama,
                              tryAgain
                            ),
                          <a href="https://ollama.com/" target="_blank">
                            Ollama
                          </a>,
                          <button
                            type="button"
                            className="link-button"
                            onClick={handleRefreshOllamaModelListClick}
                          >
                            {trans._p(
                              'Ollama hint: the button that retries listing models',
                              'Try again'
                            )}
                          </button>
                        )}
                      </div>
                    )}
                </div>
              </div>

              <div className="model-config-section-row">
                <div className="model-config-section-column">
                  <ModelPropertyList
                    properties={chatModelProperties}
                    providerId={chatModelProvider}
                    modelId={chatModel}
                    inputName="chat-model-id-input"
                    onPropertyChange={(propertyId, value) =>
                      onModelPropertyChange('chat', propertyId, value)
                    }
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Auto-complete model')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div>{trans.__('Provider')}</div>
                <div
                  title={lockedTip(
                    trans,
                    settingLocks.inline_completion_model_provider.locked
                  )}
                >
                  <select
                    className="jp-mod-styled"
                    disabled={
                      settingLocks.inline_completion_model_provider.locked
                    }
                    onChange={event =>
                      updateModelOptionsForProvider(
                        event.target.value,
                        'inline-completion'
                      )
                    }
                  >
                    {llmProviders.map((provider: any, index: number) => (
                      <option
                        key={index}
                        value={provider.id}
                        selected={provider.id === inlineCompletionModelProvider}
                      >
                        {provider.name}
                      </option>
                    ))}
                    <option
                      key={-1}
                      value="none"
                      selected={
                        inlineCompletionModelProvider === 'none' ||
                        !llmProviders.find(
                          provider =>
                            provider.id === inlineCompletionModelProvider
                        )
                      }
                    >
                      {trans._p('model provider', 'None')}
                    </option>
                  </select>
                </div>
              </div>
              {!['openai-compatible', 'litellm-compatible', 'none'].includes(
                inlineCompletionModelProvider
              ) && (
                <div className="model-config-section-column">
                  <div>{trans.__('Model')}</div>
                  {![
                    OPENAI_COMPATIBLE_INLINE_COMPLETION_MODEL_ID,
                    LITELLM_COMPATIBLE_INLINE_COMPLETION_MODEL_ID
                  ].includes(inlineCompletionModel) && (
                    <div
                      title={lockedTip(
                        trans,
                        settingLocks.inline_completion_model_id.locked
                      )}
                    >
                      <select
                        className="jp-mod-styled"
                        disabled={
                          settingLocks.inline_completion_model_id.locked
                        }
                        onChange={event =>
                          setInlineCompletionModel(event.target.value)
                        }
                      >
                        {inlineCompletionModels.map(
                          (model: any, index: number) => (
                            <option
                              key={index}
                              value={model.id}
                              selected={model.id === inlineCompletionModel}
                            >
                              {model.name}
                            </option>
                          )
                        )}
                      </select>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <ModelPropertyList
                  properties={inlineCompletionModelProperties}
                  providerId={inlineCompletionModelProvider}
                  modelId={inlineCompletionModel}
                  inputName="inline-completion-model-id-input"
                  onPropertyChange={(propertyId, value) =>
                    onModelPropertyChange(
                      'inline-completion',
                      propertyId,
                      value
                    )
                  }
                />
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section-row" style={{ width: '50%' }}>
          <div className="model-config-section-column">
            <div
              className="form-field-row"
              style={{ paddingInlineStart: '10px' }}
            >
              <div className="form-field-description">
                {trans.__('Auto-complete debouncer delay (ms)')}
              </div>
              <input
                name="inline-completion-debouncer-delay-input"
                placeholder={trans.__(
                  'Auto-complete debouncer delay (milliseconds)'
                )}
                className="jp-mod-styled"
                spellCheck={false}
                value={inlineCompletionDebouncerDelay}
                type="number"
                onChange={event =>
                  setInlineCompletionDebouncerDelay(Number(event.target.value))
                }
              />
            </div>
          </div>
        </div>

        {!isInClaudeCodeMode &&
          (chatModelProvider === 'github-copilot' ||
            inlineCompletionModelProvider === 'github-copilot') && (
            <div className="model-config-section">
              <div className="model-config-section-header access-token-config-header">
                {trans.__('GitHub Copilot login')}{' '}
                <a
                  href="https://github.com/plmbr/notebook-intelligence/blob/main/README.md#remembering-github-copilot-login"
                  target="_blank"
                >
                  {' '}
                  <VscWarning
                    className="access-token-warning"
                    title={trans.__(
                      'Click to learn more about security implications'
                    )}
                  />
                </a>
              </div>
              <div className="model-config-section-body">
                <div className="model-config-section-row">
                  <div className="model-config-section-column">
                    <label
                      title={lockedTip(
                        trans,
                        featurePolicies.store_github_access_token.locked
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checkedValue(
                          featurePolicies.store_github_access_token,
                          storeGitHubAccessToken
                        )}
                        disabled={
                          featurePolicies.store_github_access_token.locked
                        }
                        onChange={event => {
                          setStoreGitHubAccessToken(event.target.checked);
                        }}
                      />
                      {trans.__('Remember my GitHub Copilot access token')}
                    </label>
                  </div>
                </div>
              </div>
            </div>
          )}

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Cell output features')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <CheckBoxItem
                  label={trans.__('Explain cell errors')}
                  title={trans.__(
                    "Show a 'Troubleshoot errors in output' context-menu item on failed cells"
                  )}
                  checked={featurePolicies.explain_error.enabled}
                  disabled={featurePolicies.explain_error.locked}
                  tooltip={lockedTip(
                    trans,
                    featurePolicies.explain_error.locked
                  )}
                  onClick={toggleExplainError}
                />
              </div>
            </div>
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <CheckBoxItem
                  label={trans.__('Ask about cell outputs')}
                  title={trans.__(
                    'Right-click a cell output to attach it to the chat'
                  )}
                  checked={featurePolicies.output_followup.enabled}
                  disabled={featurePolicies.output_followup.locked}
                  tooltip={lockedTip(
                    trans,
                    featurePolicies.output_followup.locked
                  )}
                  onClick={toggleOutputFollowup}
                />
              </div>
            </div>
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <CheckBoxItem
                  label={trans.__('Show output toolbar')}
                  title={trans.__(
                    'Show a hover toolbar over cell outputs with Explain / Ask / Troubleshoot buttons'
                  )}
                  checked={featurePolicies.output_toolbar.enabled}
                  disabled={featurePolicies.output_toolbar.locked}
                  tooltip={lockedTip(
                    trans,
                    featurePolicies.output_toolbar.locked
                  )}
                  onClick={toggleOutputToolbar}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans._p('settings section', 'Language')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <CheckBoxItem
                  label={trans.__('Reply in my JupyterLab language')}
                  title={trans.__(
                    'Ask the AI to write its chat replies and Chatbook cell descriptions in the language JupyterLab is set to. Code, identifiers and file contents are left as they are. Has no effect while JupyterLab is in English.'
                  )}
                  checked={NBIAPI.config.replyInUserLanguage}
                  onClick={toggleReplyInUserLanguage}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('External changes')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <CheckBoxItem
                  label={trans.__('Refresh open files when changed on disk')}
                  title={trans.__(
                    'Automatically reload notebook and file editor tabs when an external process (terminal command, sync client, or AI agent) edits the file. Skipped when the tab has unsaved local edits.'
                  )}
                  checked={
                    featurePolicies.refresh_open_files_on_disk_change.enabled
                  }
                  disabled={
                    featurePolicies.refresh_open_files_on_disk_change.locked
                  }
                  tooltip={lockedTip(
                    trans,
                    featurePolicies.refresh_open_files_on_disk_change.locked
                  )}
                  onClick={toggleRefreshOpenFilesOnDiskChange}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Config file path')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <span
                  className="user-code-span"
                  onClick={() => {
                    void writeTextToClipboard(
                      path.join(NBIAPI.config.userConfigDir, 'config.json')
                    );
                    return true;
                  }}
                >
                  {path.join(NBIAPI.config.userConfigDir, 'config.json')}{' '}
                  <span
                    className="copy-icon"
                    dangerouslySetInnerHTML={{ __html: copySvgstr }}
                  ></span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingsPanelComponentMCPServers(props: any) {
  const trans = useTrans();
  const nbiConfig = NBIAPI.config;
  const mcpServersRef = useRef<any>(nbiConfig.toolConfig.mcpServers);
  const mcpServerSettingsRef = useRef<any>(nbiConfig.mcpServerSettings);
  const [renderCount, setRenderCount] = useState(1);

  const [mcpServerEnabledState, setMCPServerEnabledState] = useState(
    new Map<string, Set<string>>(
      mcpServerSettingsToEnabledState(
        mcpServersRef.current,
        mcpServerSettingsRef.current
      )
    )
  );

  const mcpServerEnabledStateToMcpServerSettings = () => {
    const mcpServerSettings: any = {};
    for (const mcpServer of mcpServersRef.current) {
      if (mcpServerEnabledState.has(mcpServer.id)) {
        const disabledTools = [];
        for (const tool of mcpServer.tools) {
          if (!mcpServerEnabledState.get(mcpServer.id).has(tool.name)) {
            disabledTools.push(tool.name);
          }
        }
        mcpServerSettings[mcpServer.id] = {
          disabled: false,
          disabled_tools: disabledTools
        };
      } else {
        mcpServerSettings[mcpServer.id] = { disabled: true };
      }
    }
    return mcpServerSettings;
  };

  const syncSettingsToServerState = () => {
    NBIAPI.setConfig({
      mcp_server_settings: mcpServerSettingsRef.current
    });
  };

  const handleReloadMCPServersClick = async () => {
    await NBIAPI.reloadMCPServers();
  };

  useEffect(() => {
    syncSettingsToServerState();
  }, [mcpServerSettingsRef.current]);

  useEffect(() => {
    mcpServerSettingsRef.current = mcpServerEnabledStateToMcpServerSettings();
    setRenderCount(renderCount => renderCount + 1);
  }, [mcpServerEnabledState]);

  const setMCPServerEnabled = (serverId: string, enabled: boolean) => {
    const currentState = new Map(mcpServerEnabledState);
    if (enabled) {
      if (!(serverId in currentState)) {
        currentState.set(
          serverId,
          new Set<string>(
            mcpServersRef.current
              .find((server: any) => server.id === serverId)
              ?.tools.map((tool: any) => tool.name)
          )
        );
      }
    } else {
      currentState.delete(serverId);
    }

    setMCPServerEnabledState(currentState);
  };

  const getMCPServerEnabled = (serverId: string) => {
    return mcpServerEnabledState.has(serverId);
  };

  const getMCPServerToolEnabled = (serverId: string, toolName: string) => {
    return (
      mcpServerEnabledState.has(serverId) &&
      mcpServerEnabledState.get(serverId).has(toolName)
    );
  };

  const setMCPServerToolEnabled = (
    serverId: string,
    toolName: string,
    enabled: boolean
  ) => {
    const currentState = new Map(mcpServerEnabledState);
    const serverState = currentState.get(serverId);
    if (enabled) {
      serverState.add(toolName);
    } else {
      serverState.delete(toolName);
    }

    setMCPServerEnabledState(currentState);
  };

  useEffect(() => {
    const handler = () => {
      mcpServersRef.current = nbiConfig.toolConfig.mcpServers;
      mcpServerSettingsRef.current = nbiConfig.mcpServerSettings;
      setRenderCount(renderCount => renderCount + 1);
    };
    NBIAPI.configChanged.connect(handler);
    return () => {
      NBIAPI.configChanged.disconnect(handler);
    };
  }, []);

  return (
    <div className="config-dialog">
      <div className="config-dialog-body">
        <div className="model-config-section">
          <div
            className="model-config-section-header"
            style={{ display: 'flex' }}
          >
            <div style={{ flexGrow: 1 }}>{trans.__('MCP Servers')}</div>
            <div>
              <button
                className="jp-toast-button jp-mod-small jp-Button"
                onClick={handleReloadMCPServersClick}
              >
                <div className="jp-Dialog-buttonLabel">
                  {trans.__('Reload')}
                </div>
              </button>
            </div>
          </div>
          <div className="model-config-section-body">
            {mcpServersRef.current.length === 0 && renderCount > 0 && (
              <div className="model-config-section-row">
                <div className="model-config-section-column">
                  <div>
                    {trans.__(
                      'No MCP servers found. Add MCP servers in the configuration file.'
                    )}
                  </div>
                </div>
              </div>
            )}
            {mcpServersRef.current.length > 0 && renderCount > 0 && (
              <div className="model-config-section-row">
                <div className="model-config-section-column">
                  {mcpServersRef.current.map((server: any) => (
                    <div key={server.id}>
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <CheckBoxItem
                          header={true}
                          label={server.id}
                          checked={getMCPServerEnabled(server.id)}
                          onClick={() => {
                            setMCPServerEnabled(
                              server.id,
                              !getMCPServerEnabled(server.id)
                            );
                          }}
                        ></CheckBoxItem>
                        <div
                          className={`server-status-indicator ${server.status}`}
                          title={mcpServerStatusTitle(trans, server.status)}
                        ></div>
                      </div>
                      {getMCPServerEnabled(server.id) && (
                        <div>
                          {server.tools.length > 0 && (
                            <div className="mcp-server-tools">
                              <div className="mcp-server-tools-header">
                                {trans.__('Tools')}
                              </div>
                              <div>
                                {server.tools.map((tool: any) => (
                                  <PillItem
                                    label={tool.name}
                                    title={tool.description}
                                    checked={getMCPServerToolEnabled(
                                      server.id,
                                      tool.name
                                    )}
                                    onClick={() => {
                                      setMCPServerToolEnabled(
                                        server.id,
                                        tool.name,
                                        !getMCPServerToolEnabled(
                                          server.id,
                                          tool.name
                                        )
                                      );
                                    }}
                                  ></PillItem>
                                ))}
                              </div>
                            </div>
                          )}
                          {server.prompts.length > 0 && (
                            <div className="mcp-server-prompts">
                              <div className="mcp-server-prompts-header">
                                {trans.__('Prompts')}
                              </div>
                              <div>
                                {server.prompts.map((prompt: any) => (
                                  <PillItem
                                    label={prompt.name}
                                    title={prompt.description}
                                    checked={true}
                                  ></PillItem>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="model-config-section-row">
              <div
                className="model-config-section-column"
                style={{ flexGrow: 'initial' }}
              >
                <button
                  className="jp-Dialog-button jp-mod-accept jp-mod-styled"
                  style={{ width: 'max-content' }}
                  onClick={props.onEditMCPConfigClicked}
                >
                  <div className="jp-Dialog-buttonLabel">
                    {trans.__('Add / Edit')}
                  </div>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function chatbookModeLabel(
  trans: TranslationBundle,
  mode: ChatbookExecutionMode
): { title: string; description: string } {
  switch (mode) {
    case 'always-confirm':
      return {
        title: trans.__('Always confirm'),
        description: trans._p(
          'Chatbook mode description; %1 and %2 are the confirm bar buttons',
          'Show the generated code and wait for %1 or %2 on every natural-language run.',
          trans._p('Chatbook confirm bar', 'Run'),
          trans._p('Chatbook confirm bar', "Don't run")
        )
      };
    case 'confirm-if-risky':
      return {
        title: trans.__('Confirm if risky'),
        description: trans.__(
          'Auto-run when a static scan looks clean. Confirm when it flags a risk or cannot parse the cell. The scan is a speed bump, not a security boundary; false negatives are inevitable.'
        )
      };
    case 'auto-run':
      return {
        title: trans.__('Auto-run'),
        description: trans.__(
          'Generate and execute immediately, same as a normal notebook cell. Inspect generated code afterward if you need to.'
        )
      };
    default: {
      // A new execution mode must get its own label: it is a security setting.
      const unknownMode: never = mode;
      return { title: unknownMode, description: '' };
    }
  }
}

function SettingsPanelComponentChatbook() {
  const trans = useTrans();
  const nbiConfig = NBIAPI.config;
  const maxMode = nbiConfig.chatbookMaxExecutionMode;
  const [executionMode, setExecutionMode] = useState<ChatbookExecutionMode>(
    nbiConfig.chatbookExecutionMode
  );
  const [llmDangerScan, setLlmDangerScan] = useState(
    nbiConfig.chatbookLlmDangerScan
  );
  const [backendKernel, setBackendKernel] = useState(
    nbiConfig.chatbookBackendKernel
  );
  const [backendProfiles, setBackendProfiles] = useState<
    INotebookKernelProfile[]
  >([]);
  const [restartHint, setRestartHint] = useState(false);

  useEffect(() => {
    const handler = () => {
      setExecutionMode(NBIAPI.config.chatbookExecutionMode);
      setLlmDangerScan(NBIAPI.config.chatbookLlmDangerScan);
      setBackendKernel(NBIAPI.config.chatbookBackendKernel);
    };
    NBIAPI.configChanged.connect(handler);
    return () => {
      NBIAPI.configChanged.disconnect(handler);
    };
  }, []);

  useEffect(() => {
    const kernels = sharedKernelSpecManager();
    void kernels.ready.then(() => {
      const profiles = listChatbookBackendProfiles(kernels.specs?.kernelspecs);
      setBackendProfiles(profiles);
      if (!NBIAPI.config.chatbookBackendKernel && profiles.length) {
        setBackendKernel(
          resolveChatbookBackendProfile(kernels.specs?.kernelspecs).kernelName
        );
      }
    });
  }, []);

  const save = (
    nextMode: ChatbookExecutionMode,
    nextLlm: boolean = llmDangerScan,
    nextBackend: string = backendKernel
  ) => {
    const mode = clampChatbookExecutionMode(nextMode, maxMode);
    setExecutionMode(mode);
    setLlmDangerScan(nextLlm);
    setBackendKernel(nextBackend);
    NBIAPI.setConfig({
      chatbook_execution_mode: mode,
      chatbook_llm_danger_scan: nextLlm,
      chatbook_backend_kernel: nextBackend
    });
  };

  const selectedBackend =
    backendProfiles.find(profile => profile.kernelName === backendKernel) ||
    resolveChatbookBackendProfile(undefined, backendKernel);

  return (
    <div className="config-dialog">
      <div className="config-dialog-body">
        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Backend kernel')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <span>
                {trans.__(
                  'Chatbook stays the notebook kernel, but generated code runs in this Jupyter kernelspec. Language, syntax highlighting, and export follow that kernel. Restart open Chatbook notebooks after changing it.'
                )}
              </span>
            </div>
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div id="nbi-chatbook-backend-kernel-label">
                  {trans.__('Execution kernel')}
                </div>
                <select
                  className="jp-mod-styled"
                  aria-labelledby="nbi-chatbook-backend-kernel-label"
                  value={backendKernel}
                  onChange={event => {
                    const next = event.target.value;
                    setRestartHint(
                      next !== NBIAPI.config.chatbookBackendKernel
                    );
                    save(executionMode, llmDangerScan, next);
                  }}
                >
                  {backendKernel &&
                    !backendProfiles.some(
                      profile => profile.kernelName === backendKernel
                    ) && (
                      <option value={backendKernel}>
                        {trans.__('%1 (not installed)', backendKernel)}
                      </option>
                    )}
                  {backendProfiles.map(profile => (
                    <option key={profile.kernelName} value={profile.kernelName}>
                      {profile.displayName} ({profile.language})
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {restartHint && (
              <div className="model-config-section-row">
                <span>
                  {trans.__(
                    'Restart the Chatbook kernel in open notebooks so they pick up %1.',
                    selectedBackend.displayName
                  )}
                </span>
              </div>
            )}
          </div>
        </div>
        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Natural-language execution')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <span>
                {trans.__(
                  'Chatbook generates %1 and runs it in %2. That process has the same privileges as any Jupyter kernel: files, network, environment variables, and package installs.',
                  selectedBackend.language,
                  selectedBackend.displayName
                )}
              </span>
            </div>
            <fieldset className="nbi-chatbook-execution-modes">
              <legend className="nbi-sr-only">
                {trans.__('Execution mode')}
              </legend>
              {CHATBOOK_EXECUTION_MODES.map(mode => {
                const spec = chatbookModeLabel(trans, mode);
                const disabled =
                  clampChatbookExecutionMode(mode, maxMode) !== mode;
                return (
                  <label
                    key={mode}
                    className="nbi-chatbook-execution-mode"
                    title={disabled ? lockedTip(trans, true) : spec.description}
                  >
                    <input
                      type="radio"
                      name="chatbook-execution-mode"
                      value={mode}
                      checked={executionMode === mode}
                      disabled={disabled}
                      onChange={() => save(mode)}
                    />
                    <span>
                      <strong>{spec.title}</strong>
                      <span className="nbi-chatbook-execution-mode-help">
                        {spec.description}
                      </span>
                    </span>
                  </label>
                );
              })}
            </fieldset>
            {executionMode === 'confirm-if-risky' && (
              <div className="model-config-section-row">
                <CheckBoxItem
                  label={trans.__('Also classify with the chat model')}
                  title={trans.__(
                    'Optional extra check. A static scan hit always wins; the model can only raise risk. Classifier failures confirm instead of auto-running.'
                  )}
                  checked={llmDangerScan}
                  onClick={() => save(executionMode, !llmDangerScan)}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingsPanelComponentClaude(props: any) {
  const trans = useTrans();
  const nbiConfig = NBIAPI.config;
  const claudeSettingsRef = useRef<any>(nbiConfig.claudeSettings);
  const [_renderCount, setRenderCount] = useState(1);
  const [claudeEnabled, setClaudeEnabled] = useState(
    nbiConfig.claudeSettings?.enabled === true
  );
  const [chatModel, setChatModel] = useState(
    nbiConfig.claudeSettings.chat_model ?? ClaudeModelType.Default
  );
  // Optional override for the inline chat popover, which calls the Anthropic
  // API directly rather than going through the Claude Code CLI. Empty means
  // "fall back to chat_model", which is what the backend resolves.
  const [inlineChatModel, setInlineChatModel] = useState(
    nbiConfig.claudeSettings.inline_chat_model ?? ClaudeModelType.Default
  );
  // Collapsed by default — it is an override on the Chat model above and most
  // users never set it — but opened when one is already configured, so a
  // non-default model is never hidden behind a closed disclosure.
  const [inlineChatModelExpanded, setInlineChatModelExpanded] = useState(
    inlineChatModel !== ClaudeModelType.Default
  );
  const [inlineCompletionModel, setInlineCompletionModel] = useState(
    nbiConfig.claudeSettings.inline_completion_model ?? ClaudeModelType.Default
  );
  const [apiKey, setApiKey] = useState(nbiConfig.claudeSettings.api_key ?? '');
  const [baseUrl, setBaseUrl] = useState(
    nbiConfig.claudeSettings.base_url ?? ''
  );
  const [settingSources, setSettingSources] = useState(
    nbiConfig.claudeSettings.setting_sources ?? []
  );
  const [tools, setTools] = useState(
    nbiConfig.claudeSettings.tools ?? [
      ClaudeToolType.ClaudeCodeTools,
      ClaudeToolType.JupyterUITools
    ]
  );
  const [continueConversation, setContinueConversation] = useState(
    nbiConfig.claudeSettings.continue_conversation ?? false
  );
  const [showTurnUsage, setShowTurnUsage] = useState(
    nbiConfig.claudeSettings.show_turn_usage ?? false
  );
  const [claudeModels, setClaudeModels] = useState<IClaudeModelInfo[]>(
    nbiConfig.claudeModels
  );
  const [loadingModels, setLoadingModels] = useState(false);
  const { featurePolicies, settingLocks } = useNbiPolicies();

  useEffect(() => {
    const handler = () => {
      claudeSettingsRef.current = nbiConfig.claudeSettings;
      setClaudeModels(nbiConfig.claudeModels);
      setRenderCount(renderCount => renderCount + 1);
    };
    NBIAPI.configChanged.connect(handler);
    return () => {
      NBIAPI.configChanged.disconnect(handler);
    };
  }, []);

  const refreshClaudeModels = async () => {
    setLoadingModels(true);
    try {
      await NBIAPI.updateClaudeModelList();
      const models = nbiConfig.claudeModels;
      console.log('claude_models after refresh:', models);
      setClaudeModels(models);
    } finally {
      setLoadingModels(false);
    }
  };

  const syncSettingsToServerState = () => {
    NBIAPI.setConfig({
      claude_settings: {
        enabled: claudeEnabled,
        chat_model: chatModel,
        inline_chat_model: inlineChatModel,
        inline_completion_model: inlineCompletionModel,
        api_key: apiKey,
        base_url: baseUrl,
        setting_sources: settingSources,
        tools: tools,
        continue_conversation: continueConversation,
        show_turn_usage: showTurnUsage
      }
    });
  };

  useEffect(() => {
    syncSettingsToServerState();
  }, [
    claudeEnabled,
    chatModel,
    inlineChatModel,
    inlineCompletionModel,
    apiKey,
    baseUrl,
    settingSources,
    tools,
    continueConversation,
    showTurnUsage
  ]);

  return (
    <div className="config-dialog claude-mode-config-dialog">
      <div className="config-dialog-body">
        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Enable Claude mode')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <span>
                {interpolate(
                  (claude, claudeCode) =>
                    trans.__(
                      'This requires a %1 account and %2 installed in your system.',
                      claude,
                      claudeCode
                    ),
                  <a href="https://claude.ai" target="_blank">
                    Claude
                  </a>,
                  <a href="https://code.claude.com/" target="_blank">
                    Claude Code
                  </a>
                )}
              </span>
            </div>
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    header={true}
                    label={trans.__('Enable Claude mode')}
                    checked={checkedValue(
                      featurePolicies.claude_mode,
                      claudeEnabled
                    )}
                    disabled={featurePolicies.claude_mode.locked}
                    tooltip={lockedTip(
                      trans,
                      featurePolicies.claude_mode.locked
                    )}
                    onClick={() => {
                      setClaudeEnabled(!claudeEnabled);
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div
            className="model-config-section-header"
            style={{ display: 'flex' }}
          >
            <div style={{ flexGrow: 1 }}>{trans.__('Models')}</div>
            <div>
              <button
                className="jp-toast-button jp-mod-small jp-Button"
                onClick={refreshClaudeModels}
                disabled={loadingModels}
              >
                <div className="jp-Dialog-buttonLabel">
                  {loadingModels ? trans.__('Loading...') : trans.__('Refresh')}
                </div>
              </button>
            </div>
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div id="nbi-claude-chat-model-label">
                  {trans.__('Chat model')}
                </div>
                <div
                  title={lockedTip(
                    trans,
                    settingLocks.claude_chat_model.locked
                  )}
                >
                  <select
                    className="jp-mod-styled"
                    aria-labelledby="nbi-claude-chat-model-label"
                    aria-describedby={
                      settingLocks.claude_chat_model.locked
                        ? 'nbi-claude-chat-model-lock-reason'
                        : undefined
                    }
                    disabled={settingLocks.claude_chat_model.locked}
                    value={chatModel}
                    onChange={event => setChatModel(event.target.value)}
                  >
                    <option value={ClaudeModelType.Default}>
                      {trans.__('Default (recommended)')}
                    </option>
                    {/* Placeholder for a persisted model id that hasn't
                        landed in `claudeModels` yet (empty cache, no api
                        key, mid-fetch). Rendered just after Default so
                        the active value sits near the top of the list. */}
                    {chatModel !== ClaudeModelType.Default &&
                      !claudeModels.some(m => m.id === chatModel) && (
                        <option key={chatModel} value={chatModel}>
                          {chatModel}
                        </option>
                      )}
                    {claudeModels.map(model => (
                      <option key={model.id} value={model.id}>
                        {model.name}
                      </option>
                    ))}
                  </select>
                  {settingLocks.claude_chat_model.locked && (
                    <span
                      id="nbi-claude-chat-model-lock-reason"
                      className="nbi-sr-only"
                    >
                      {lockedTip(trans, true)}
                    </span>
                  )}
                </div>
                {/* Nested under Chat model because it overrides that value,
                    and collapsed because most users never set it. Pinned by
                    NBI_CLAUDE_INLINE_CHAT_MODEL. */}
                <div
                  className={`expandable-content nbi-sub-setting${
                    inlineChatModelExpanded ? ' expanded' : ''
                  }`}
                >
                  <button
                    type="button"
                    className="expandable-content-title"
                    onClick={() =>
                      setInlineChatModelExpanded(expanded => !expanded)
                    }
                    aria-expanded={inlineChatModelExpanded}
                    aria-controls="nbi-claude-inline-chat-model-body"
                  >
                    <VscTriangleRight
                      className="collapsed-icon"
                      aria-hidden="true"
                    />
                    <VscTriangleDown
                      className="expanded-icon"
                      aria-hidden="true"
                    />{' '}
                    {trans.__('Inline chat model')}
                  </button>
                  <div
                    id="nbi-claude-inline-chat-model-body"
                    className="nbi-sub-setting-body"
                  >
                    <div
                      title={lockedTip(
                        trans,
                        settingLocks.claude_inline_chat_model.locked
                      )}
                    >
                      <select
                        className="jp-mod-styled"
                        aria-label={trans.__('Inline chat model')}
                        disabled={settingLocks.claude_inline_chat_model.locked}
                        value={inlineChatModel}
                        onChange={event =>
                          setInlineChatModel(event.target.value)
                        }
                      >
                        <option value={ClaudeModelType.Default}>
                          {trans.__('Inherit from chat model')}
                        </option>
                        {/* Same placeholder rule as the Chat model dropdown. */}
                        {inlineChatModel !== ClaudeModelType.Default &&
                          !claudeModels.some(m => m.id === inlineChatModel) && (
                            <option
                              key={inlineChatModel}
                              value={inlineChatModel}
                            >
                              {inlineChatModel}
                            </option>
                          )}
                        {claudeModels.map(model => (
                          <option key={model.id} value={model.id}>
                            {model.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>
              </div>
              <div className="model-config-section-column">
                <div id="nbi-claude-inline-model-label">
                  {trans.__('Auto-complete model')}
                </div>
                <div
                  title={lockedTip(
                    trans,
                    settingLocks.claude_inline_completion_model.locked
                  )}
                >
                  <select
                    className="jp-mod-styled"
                    aria-labelledby="nbi-claude-inline-model-label"
                    aria-describedby={
                      settingLocks.claude_inline_completion_model.locked
                        ? 'nbi-claude-inline-model-lock-reason'
                        : undefined
                    }
                    disabled={
                      settingLocks.claude_inline_completion_model.locked
                    }
                    value={inlineCompletionModel}
                    onChange={event =>
                      setInlineCompletionModel(event.target.value)
                    }
                  >
                    <option value={ClaudeModelType.None}>
                      {trans._p('model', 'None')}
                    </option>
                    <option value={ClaudeModelType.Inherit}>
                      {trans.__('Inherit from general settings')}
                    </option>
                    <option value={ClaudeModelType.Default}>
                      {trans.__('Default (recommended)')}
                    </option>
                    {![
                      ClaudeModelType.None,
                      ClaudeModelType.Inherit,
                      ClaudeModelType.Default
                    ].includes(inlineCompletionModel as ClaudeModelType) &&
                      !claudeModels.some(
                        m => m.id === inlineCompletionModel
                      ) && (
                        <option
                          key={inlineCompletionModel}
                          value={inlineCompletionModel}
                        >
                          {inlineCompletionModel}
                        </option>
                      )}
                    {claudeModels.map(model => (
                      <option key={model.id} value={model.id}>
                        {model.name}
                      </option>
                    ))}
                  </select>
                  {settingLocks.claude_inline_completion_model.locked && (
                    <span
                      id="nbi-claude-inline-model-lock-reason"
                      className="nbi-sr-only"
                    >
                      {lockedTip(trans, true)}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Chat Agent setting sources')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    header={true}
                    label={trans._p('setting source', 'User')}
                    checked={checkedValue(
                      featurePolicies.claude_setting_source_user,
                      settingSources.includes('user')
                    )}
                    disabled={featurePolicies.claude_setting_source_user.locked}
                    tooltip={lockedTip(
                      trans,
                      featurePolicies.claude_setting_source_user.locked
                    )}
                    onClick={() => {
                      setSettingSources(
                        settingSources.includes('user')
                          ? settingSources.filter(
                              (source: string) => source !== 'user'
                            )
                          : [...settingSources, 'user']
                      );
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    header={true}
                    label={trans.__('Project (Jupyter root directory)')}
                    checked={checkedValue(
                      featurePolicies.claude_setting_source_project,
                      settingSources.includes('project')
                    )}
                    disabled={
                      featurePolicies.claude_setting_source_project.locked
                    }
                    tooltip={lockedTip(
                      trans,
                      featurePolicies.claude_setting_source_project.locked
                    )}
                    onClick={() => {
                      setSettingSources(
                        settingSources.includes('project')
                          ? settingSources.filter(
                              (source: string) => source !== 'project'
                            )
                          : [...settingSources, 'project']
                      );
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Chat Agent tools')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    header={true}
                    label={trans.__('Claude Code tools')}
                    checked={checkedValue(
                      featurePolicies.claude_code_tools,
                      tools.includes(ClaudeToolType.ClaudeCodeTools)
                    )}
                    disabled={true}
                    tooltip={lockedTip(
                      trans,
                      featurePolicies.claude_code_tools.locked
                    )}
                    onClick={() => {
                      setTools(
                        tools.includes(ClaudeToolType.ClaudeCodeTools)
                          ? tools.filter(
                              (tool: string) =>
                                tool !== ClaudeToolType.ClaudeCodeTools
                            )
                          : [...tools, ClaudeToolType.ClaudeCodeTools]
                      );
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    header={true}
                    label={trans.__('Jupyter UI tools')}
                    checked={checkedValue(
                      featurePolicies.claude_jupyter_ui_tools,
                      tools.includes(ClaudeToolType.JupyterUITools)
                    )}
                    disabled={featurePolicies.claude_jupyter_ui_tools.locked}
                    tooltip={lockedTip(
                      trans,
                      featurePolicies.claude_jupyter_ui_tools.locked
                    )}
                    onClick={() => {
                      setTools(
                        tools.includes(ClaudeToolType.JupyterUITools)
                          ? tools.filter(
                              (tool: string) =>
                                tool !== ClaudeToolType.JupyterUITools
                            )
                          : [...tools, ClaudeToolType.JupyterUITools]
                      );
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Conversation History')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    header={true}
                    label={trans.__('Remember conversation history')}
                    checked={checkedValue(
                      featurePolicies.claude_continue_conversation,
                      continueConversation
                    )}
                    disabled={
                      featurePolicies.claude_continue_conversation.locked
                    }
                    tooltip={lockedTip(
                      trans,
                      featurePolicies.claude_continue_conversation.locked
                    )}
                    onClick={() => {
                      setContinueConversation(!continueConversation);
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Usage footer')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    header={true}
                    label={trans.__(
                      'Show usage after each turn (time / tokens / cost)'
                    )}
                    title={trans.__('Adds a small footer under each reply.')}
                    checked={showTurnUsage}
                    onClick={() => {
                      setShowTurnUsage(!showTurnUsage);
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Claude account')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div className="form-field-row">
                  <div className="form-field-description">
                    {optionalLabel(trans, trans.__('API Key'))}
                  </div>
                  <input
                    name="chat-model-id-input"
                    type="password"
                    autoComplete="new-password"
                    placeholder={
                      settingLocks.claude_api_key.locked
                        ? lockedByEnvironmentTip(trans, 'ANTHROPIC_API_KEY')
                        : trans.__('API Key')
                    }
                    className="jp-mod-styled"
                    spellCheck={false}
                    value={settingLocks.claude_api_key.locked ? '' : apiKey}
                    disabled={settingLocks.claude_api_key.locked}
                    title={lockedTip(trans, settingLocks.claude_api_key.locked)}
                    onFocus={selectMask}
                    onChange={event => setApiKey(event.target.value)}
                  />
                </div>
                <div className="form-field-row">
                  <div className="form-field-description">
                    {optionalLabel(trans, trans.__('Base URL'))}
                  </div>
                  <input
                    name="chat-model-id-input"
                    placeholder={
                      settingLocks.claude_base_url.locked
                        ? lockedByEnvironmentTip(trans, 'ANTHROPIC_BASE_URL')
                        : 'https://api.anthropic.com'
                    }
                    className="jp-mod-styled"
                    spellCheck={false}
                    value={baseUrl}
                    disabled={settingLocks.claude_base_url.locked}
                    title={lockedTip(
                      trans,
                      settingLocks.claude_base_url.locked
                    )}
                    onChange={event => setBaseUrl(event.target.value)}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingsPanelComponentAcp(props: any) {
  const trans = useTrans();
  const nbiConfig = NBIAPI.config;
  const acpAgents = nbiConfig.acpAgents;
  const [acpEnabled, setAcpEnabled] = useState(
    nbiConfig.acpSettings?.enabled === true
  );
  const [agent, setAgent] = useState(
    nbiConfig.acpSettings.agent ?? acpAgents[0]?.id ?? 'codex'
  );
  const [chatModel, setChatModel] = useState(
    nbiConfig.acpSettings.chat_model ?? ''
  );
  const [apiKey, setApiKey] = useState(nbiConfig.acpSettings.api_key ?? '');
  const [baseUrl, setBaseUrl] = useState(nbiConfig.acpSettings.base_url ?? '');
  const [fullAccess, setFullAccess] = useState(
    nbiConfig.acpSettings.full_access === true
  );
  const { featurePolicies, settingLocks } = useNbiPolicies();

  const syncSettingsToServerState = () => {
    NBIAPI.setConfig({
      acp_settings: {
        enabled: acpEnabled,
        agent: agent,
        chat_model: chatModel,
        api_key: apiKey,
        base_url: baseUrl,
        full_access: fullAccess
      }
    });
  };

  useEffect(() => {
    syncSettingsToServerState();
  }, [acpEnabled, agent, chatModel, apiKey, baseUrl, fullAccess]);

  return (
    <div className="config-dialog acp-mode-config-dialog">
      <div className="config-dialog-body">
        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Enable ACP mode')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <span>
                {interpolate(
                  (protocol, adapter, pkg, guide) =>
                    trans.__(
                      'Experimental. Routes chat through an external coding agent over the %1. Requires a preinstalled %2 adapter (%3). See the %4. ACP mode and Claude mode are mutually exclusive: enabling one turns the other off.',
                      protocol,
                      adapter,
                      pkg,
                      guide
                    ),
                  <a
                    href="https://agentclientprotocol.com/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Agent Client Protocol
                  </a>,
                  <code>codex-acp</code>,
                  <code>@zed-industries/codex-acp@0.16.0</code>,
                  <a
                    href="https://github.com/plmbr/notebook-intelligence/blob/main/docs/admin-guide.md#gating-the-experimental-acp-agent-378"
                    target="_blank"
                    rel="noreferrer"
                  >
                    {trans._p(
                      'ACP description: the link to the admin guide',
                      'administrator installation guide'
                    )}
                  </a>
                )}
              </span>
            </div>
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    header={true}
                    label={trans.__('Enable ACP mode')}
                    checked={checkedValue(featurePolicies.acp_mode, acpEnabled)}
                    disabled={featurePolicies.acp_mode.locked}
                    tooltip={lockedTip(trans, featurePolicies.acp_mode.locked)}
                    onClick={() => {
                      setAcpEnabled(!acpEnabled);
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
            </div>
            <div className="model-config-section-row">
              <span id="acp-full-access-warning" className="config-warning">
                {trans.__(
                  'By default the agent asks before anything beyond trusted read-only commands. Full access lets it edit workspace files and run shell commands without asking, in a sandbox with network access off by default. Anything the sandbox blocks fails instead of prompting. Content the agent reads can steer what it runs.'
                )}
              </span>
            </div>
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div>
                  <CheckBoxItem
                    label={trans.__('Full access (run without asking)')}
                    ariaDescribedBy="acp-full-access-warning"
                    checked={checkedValue(
                      featurePolicies.acp_full_access,
                      fullAccess
                    )}
                    disabled={featurePolicies.acp_full_access.locked}
                    tooltip={lockedTip(
                      trans,
                      featurePolicies.acp_full_access.locked
                    )}
                    onClick={() => {
                      setFullAccess(!fullAccess);
                    }}
                  ></CheckBoxItem>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans._p('ACP settings section', 'Agent')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div className="form-field-row">
                  <div
                    className="form-field-description"
                    id="acp-agent-select-label"
                  >
                    {trans.__('Agent type')}
                  </div>
                  <select
                    name="acp-agent-select"
                    aria-labelledby="acp-agent-select-label"
                    className="jp-mod-styled"
                    value={agent}
                    onChange={event => setAgent(event.target.value)}
                  >
                    {acpAgents.map(a => (
                      <option key={a.id} value={a.id}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-field-row">
                  <div className="form-field-description">
                    {optionalLabel(trans, trans.__('Chat model'))}
                  </div>
                  <input
                    name="acp-chat-model-input"
                    placeholder={
                      settingLocks.acp_chat_model.locked
                        ? lockedByEnvironmentTip(trans, 'NBI_ACP_CHAT_MODEL')
                        : trans.__("Agent default (e.g. '%1')", 'gpt-5-codex')
                    }
                    className="jp-mod-styled"
                    spellCheck={false}
                    value={settingLocks.acp_chat_model.locked ? '' : chatModel}
                    disabled={settingLocks.acp_chat_model.locked}
                    title={lockedTip(trans, settingLocks.acp_chat_model.locked)}
                    onChange={event => setChatModel(event.target.value)}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="model-config-section">
          <div className="model-config-section-header">
            {trans.__('Agent account')}
          </div>
          <div className="model-config-section-body">
            <div className="model-config-section-row">
              <div className="model-config-section-column">
                <div className="form-field-row">
                  <div className="form-field-description">
                    {optionalLabel(trans, trans.__('API Key'))}
                  </div>
                  <input
                    name="acp-api-key-input"
                    type="password"
                    autoComplete="new-password"
                    placeholder={
                      settingLocks.acp_api_key.locked
                        ? lockedByEnvironmentTip(trans, 'OPENAI_API_KEY')
                        : trans.__('API Key')
                    }
                    className="jp-mod-styled"
                    spellCheck={false}
                    value={settingLocks.acp_api_key.locked ? '' : apiKey}
                    disabled={settingLocks.acp_api_key.locked}
                    title={lockedTip(trans, settingLocks.acp_api_key.locked)}
                    onFocus={selectMask}
                    onChange={event => setApiKey(event.target.value)}
                  />
                </div>
                <div className="form-field-row">
                  <div className="form-field-description">
                    {optionalLabel(trans, trans.__('Base URL'))}
                  </div>
                  <input
                    name="acp-base-url-input"
                    placeholder={
                      settingLocks.acp_base_url.locked
                        ? lockedByEnvironmentTip(trans, 'OPENAI_BASE_URL')
                        : 'https://api.openai.com/v1'
                    }
                    className="jp-mod-styled"
                    spellCheck={false}
                    value={settingLocks.acp_base_url.locked ? '' : baseUrl}
                    disabled={settingLocks.acp_base_url.locked}
                    title={lockedTip(trans, settingLocks.acp_base_url.locked)}
                    onChange={event => setBaseUrl(event.target.value)}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
