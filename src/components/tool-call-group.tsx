import React, { useState } from 'react';
import { VscChevronDown, VscChevronRight } from '../icons';
import { IToolCall, ToolCallCard } from './tool-call-card';

// Groups with more calls than this start collapsed so a tool-heavy turn (or a
// reloaded transcript) doesn't flood the chat. A live turn mounts the group at
// length 1, so it starts expanded and stays visible as calls stream in.
const GROUP_COLLAPSE_THRESHOLD = 3;

/**
 * Renders a run of consecutive tool calls. A single call is shown as a bare
 * card; multiple calls are wrapped in one collapsible group with a summary
 * header, so consecutive agent activity reads as one unit instead of a wall
 * of rows.
 */
export function ToolCallGroup(props: { toolCalls: IToolCall[] }): JSX.Element {
  const { toolCalls } = props;
  // Hooks must run unconditionally and in a stable order: the group's length
  // grows as calls stream in, so call useState before any length branch.
  // Start collapsed only for a large group whose calls are all settled --
  // never hide a still-running or failed call (matters on transcript reload,
  // where a group can mount already large).
  const [expanded, setExpanded] = useState(
    () =>
      toolCalls.length <= GROUP_COLLAPSE_THRESHOLD ||
      toolCalls.some(t => t.status === 'in_progress' || t.status === 'failed')
  );

  if (toolCalls.length <= 1) {
    return toolCalls.length === 1 ? (
      <ToolCallCard toolCall={toolCalls[0]} />
    ) : (
      <></>
    );
  }

  const failed = toolCalls.filter(t => t.status === 'failed').length;
  const summary =
    `${toolCalls.length} tool calls` + (failed ? ` (${failed} failed)` : '');

  return (
    <div className="nbi-tool-call-group">
      <button
        type="button"
        className="nbi-tool-call-group-header"
        onClick={() => setExpanded(e => !e)}
        aria-expanded={expanded}
      >
        {expanded ? (
          <VscChevronDown aria-hidden="true" />
        ) : (
          <VscChevronRight aria-hidden="true" />
        )}
        <span className="nbi-tool-call-group-summary">{summary}</span>
      </button>
      {expanded ? (
        <div className="nbi-tool-call-group-body">
          {toolCalls.map(toolCall => (
            <ToolCallCard key={toolCall.id} toolCall={toolCall} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
