// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React, { useEffect, useRef, useState } from 'react';
import { VscCheck, VscChevronDown } from '../icons';
import claudeSvgStr from '../../style/icons/claude.svg';
import openaiSvgStr from '../../style/icons/openai.svg';

// Per-agent display metadata. `className` carries the brand color (the same
// rules the settings tabs and chat avatars use). Adding an ACP agent here +
// the backend priority list is all the picker needs.
const AGENT_META: Record<
  string,
  { label: string; svg: string; className: string }
> = {
  claude: { label: 'Claude', svg: claudeSvgStr, className: 'claude-icon' },
  codex: { label: 'Codex', svg: openaiSvgStr, className: 'codex-icon' }
};

function labelFor(mode: string): string {
  return AGENT_META[mode]?.label ?? mode;
}

function AgentIcon({ mode }: { mode: string }): JSX.Element | null {
  const meta = AGENT_META[mode];
  if (!meta) {
    return null;
  }
  return (
    <span
      className={`agent-select-icon ${meta.className}`}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: meta.svg }}
    ></span>
  );
}

export interface IAgentSelectProps {
  value: string;
  agents: string[];
  onChange: (mode: string) => void;
}

/**
 * Active-agent picker shown in the chat header when more than one agent mode
 * is enabled (#378). A compact icon + name dropdown so the choice reads at a
 * glance and stays consistent with the agent badges elsewhere; native
 * <select> cannot render the per-agent SVG marks. Mirrors the keyboard /
 * focus behavior of the permission-mode selector.
 */
export function AgentSelect(props: IAgentSelectProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleClickOutside = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  // Land focus on the active item when the menu opens.
  useEffect(() => {
    if (open) {
      menuRef.current
        ?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
        ?.focus();
    }
  }, [open]);

  const closeMenu = (restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) {
      buttonRef.current?.focus();
    }
  };

  const choose = (mode: string) => {
    closeMenu();
    if (mode !== props.value) {
      props.onChange(mode);
    }
  };

  return (
    <div className="agent-select-container" ref={containerRef}>
      <button
        type="button"
        ref={buttonRef}
        className="agent-select-button jp-mod-styled"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Active agent: ${labelFor(props.value)}`}
        title="Choose which agent handles chat"
        onClick={() => setOpen(o => !o)}
      >
        <AgentIcon mode={props.value} />
        <span className="agent-select-button-label">
          {labelFor(props.value)}
        </span>
        <VscChevronDown aria-hidden="true" />
      </button>
      {open && (
        <div
          className="agent-select-menu"
          role="menu"
          ref={menuRef}
          aria-label="Active agent"
          onKeyDown={event => {
            if (event.key === 'Escape') {
              event.stopPropagation();
              closeMenu();
              return;
            }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault();
              const items = Array.from(
                menuRef.current?.querySelectorAll<HTMLButtonElement>(
                  '[role="menuitemradio"]'
                ) ?? []
              );
              const current = items.indexOf(
                document.activeElement as HTMLButtonElement
              );
              const delta = event.key === 'ArrowDown' ? 1 : -1;
              const next = (current + delta + items.length) % items.length;
              items[next]?.focus();
            }
          }}
        >
          {props.agents.map(mode => {
            const selected = props.value === mode;
            return (
              <button
                type="button"
                key={mode}
                role="menuitemradio"
                aria-checked={selected}
                tabIndex={selected ? 0 : -1}
                className="agent-select-menu-item"
                onClick={() => choose(mode)}
              >
                <span className="agent-select-menu-check">
                  {selected && <VscCheck aria-hidden="true" />}
                </span>
                <AgentIcon mode={mode} />
                {labelFor(mode)}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
