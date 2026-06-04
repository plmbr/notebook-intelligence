import React, { useState } from 'react';
import {
  VscChevronDown,
  VscChevronRight,
  VscClose,
  VscEdit,
  VscError,
  VscEye,
  VscPassFilled,
  VscSync,
  VscTerminal,
  VscTools
} from '../icons';

export interface IToolCallDiffLine {
  type: 'add' | 'remove' | 'context' | string;
  content: string;
}

export interface IToolCallDiff {
  path: string;
  lines: IToolCallDiffLine[];
  truncated?: boolean;
}

/**
 * A single agent tool call surfaced as a persistent chat card. Mirrors the
 * `ToolCallData` payload emitted by the server: it stays in the transcript
 * after the turn ends and carries its final status, unlike the transient
 * single progress line it replaces. File-edit tools also carry inline diffs.
 */
export interface IToolCall {
  id: string;
  title: string;
  // Coarse category, used only to pick the leading icon.
  kind: 'read' | 'edit' | 'execute' | 'other' | string;
  status: 'in_progress' | 'completed' | 'failed' | 'cancelled' | string;
  diffs?: IToolCallDiff[];
}

const KIND_ICONS: Record<string, React.FC<any>> = {
  read: VscEye,
  edit: VscEdit,
  execute: VscTerminal,
  other: VscTools
};

const STATUS_LABELS: Record<string, string> = {
  in_progress: 'in progress',
  completed: 'completed',
  failed: 'failed',
  cancelled: 'cancelled'
};

const GUTTER: Record<string, string> = { add: '+', remove: '-' };

function ToolCallDiffView(props: { diffs: IToolCallDiff[] }): JSX.Element {
  return (
    <div className="nbi-tool-call-diffs">
      {props.diffs.map((diff, i) => (
        <div className="nbi-tool-call-diff" key={i}>
          {diff.path ? (
            <div className="nbi-tool-call-diff-path" title={diff.path}>
              {diff.path}
            </div>
          ) : null}
          <div className="nbi-tool-call-diff-body">
            {diff.lines.map((line, j) => (
              <div
                className={`nbi-tool-call-diff-line nbi-diff-${line.type}`}
                key={j}
              >
                <span className="nbi-diff-gutter" aria-hidden="true">
                  {GUTTER[line.type] ?? ' '}
                </span>
                {/* The +/- gutter is decorative; give screen readers the
                    add/remove distinction as text instead. */}
                {line.type === 'add' || line.type === 'remove' ? (
                  <span className="nbi-sr-only">
                    {line.type === 'add' ? 'added ' : 'removed '}
                  </span>
                ) : null}
                <span className="nbi-diff-text">{line.content}</span>
              </div>
            ))}
          </div>
          {diff.truncated ? (
            <div className="nbi-tool-call-diff-truncated">diff truncated</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function ToolCallCard(props: { toolCall: IToolCall }): JSX.Element {
  const { title, kind, status, diffs } = props.toolCall;
  const [expanded, setExpanded] = useState(true);

  const KindIcon = KIND_ICONS[kind] ?? VscTools;

  let StatusIcon = VscSync;
  if (status === 'completed') {
    StatusIcon = VscPassFilled;
  } else if (status === 'failed') {
    StatusIcon = VscError;
  } else if (status === 'cancelled') {
    StatusIcon = VscClose;
  }

  const statusLabel = STATUS_LABELS[status] ?? status;
  const statusModifier = status.replace(/_/g, '-');
  const hasDiffs = Array.isArray(diffs) && diffs.length > 0;

  return (
    <div className="nbi-tool-call-wrapper">
      <div className={`nbi-tool-call nbi-tool-call-${statusModifier}`}>
        <KindIcon className="nbi-tool-call-kind-icon" aria-hidden="true" />
        <span className="nbi-tool-call-title" title={title}>
          {title}
        </span>
        {hasDiffs ? (
          <button
            type="button"
            className="nbi-tool-call-diff-toggle"
            onClick={() => setExpanded(e => !e)}
            aria-expanded={expanded}
            aria-label={expanded ? 'Hide diff' : 'Show diff'}
          >
            {expanded ? (
              <VscChevronDown aria-hidden="true" />
            ) : (
              <VscChevronRight aria-hidden="true" />
            )}
          </button>
        ) : null}
        <StatusIcon className="nbi-tool-call-status-icon" aria-hidden="true" />
        {/* Status reaches screen readers as text; the icons are decorative.
            The visible title is already in the accessibility tree, so this
            span carries only the status to avoid announcing the title twice. */}
        <span className="nbi-sr-only">{statusLabel}</span>
      </div>
      {hasDiffs && expanded ? <ToolCallDiffView diffs={diffs!} /> : null}
    </div>
  );
}
