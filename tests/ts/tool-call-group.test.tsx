import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ToolCallGroup } from '../../src/components/tool-call-group';

function calls(n: number, status = 'completed') {
  return Array.from({ length: n }, (_, i) => ({
    id: `t${i}`,
    title: `Tool ${i}`,
    kind: 'read',
    status
  }));
}

describe('ToolCallGroup', () => {
  it('renders a single call as a bare card with no group header', () => {
    const { container } = render(<ToolCallGroup toolCalls={calls(1)} />);
    expect(container.querySelector('.nbi-tool-call')).toBeInTheDocument();
    expect(
      container.querySelector('.nbi-tool-call-group-header')
    ).not.toBeInTheDocument();
  });

  it('wraps multiple calls in a group with a count summary', () => {
    render(<ToolCallGroup toolCalls={calls(3)} />);
    expect(screen.getByText('3 tool calls')).toBeInTheDocument();
  });

  it('starts expanded for a small group and toggles closed', () => {
    const { container } = render(<ToolCallGroup toolCalls={calls(3)} />);
    expect(container.querySelectorAll('.nbi-tool-call')).toHaveLength(3);
    fireEvent.click(screen.getByRole('button'));
    expect(container.querySelectorAll('.nbi-tool-call')).toHaveLength(0);
  });

  it('starts collapsed for a large group (over the threshold)', () => {
    const { container } = render(<ToolCallGroup toolCalls={calls(5)} />);
    expect(container.querySelectorAll('.nbi-tool-call')).toHaveLength(0);
    expect(screen.getByText('5 tool calls')).toBeInTheDocument();
    // Expanding reveals all cards.
    fireEvent.click(screen.getByRole('button'));
    expect(container.querySelectorAll('.nbi-tool-call')).toHaveLength(5);
  });

  it('stays stable and expanded as the group grows from 1 across rerenders', () => {
    // A live turn mounts the group at length 1 and grows it; useState runs
    // before the length<=1 early return, so the hook order must stay stable
    // (a violation would throw "rendered more/fewer hooks").
    const { container, rerender } = render(
      <ToolCallGroup toolCalls={calls(1)} />
    );
    expect(
      container.querySelector('.nbi-tool-call-group-header')
    ).not.toBeInTheDocument();

    expect(() => {
      rerender(<ToolCallGroup toolCalls={calls(2)} />);
      rerender(<ToolCallGroup toolCalls={calls(4)} />);
    }).not.toThrow();

    // It became a group and, having mounted small (expanded), stays expanded
    // even though it grew past the collapse threshold.
    expect(
      container.querySelector('.nbi-tool-call-group-header')
    ).toBeInTheDocument();
    expect(container.querySelectorAll('.nbi-tool-call')).toHaveLength(4);
  });

  it('stays expanded when its calls settle on a persistent instance (no self-collapse)', () => {
    // Guards the component contract the #363 fix relies on: a group that
    // mounted expanded must not collapse itself when its calls later settle
    // (the collapsed-default heuristic runs only at mount, never on update).
    // The remount that actually caused the flicker is fixed in the sidebar
    // render (stable message and group keys) and is verified live, not here --
    // rerender keeps this same instance mounted, the post-fix steady state.
    const live = [...calls(3, 'completed'), ...calls(1, 'in_progress')].map(
      (c, i) => ({ ...c, id: `s${i}` })
    );
    const { container, rerender } = render(<ToolCallGroup toolCalls={live} />);
    expect(container.querySelectorAll('.nbi-tool-call')).toHaveLength(4);

    const settled = live.map(c => ({ ...c, status: 'completed' }));
    rerender(<ToolCallGroup toolCalls={settled} />);
    // 4 settled calls (> threshold) would start collapsed on a fresh mount;
    // this instance mounted expanded and must not collapse itself.
    expect(container.querySelectorAll('.nbi-tool-call')).toHaveLength(4);
  });

  it('starts expanded when a large group still has an in-progress call', () => {
    const live = [...calls(4, 'completed'), ...calls(1, 'in_progress')].map(
      (c, i) => ({ ...c, id: `u${i}` })
    );
    const { container } = render(<ToolCallGroup toolCalls={live} />);
    // 5 calls (> threshold) would normally start collapsed, but the pending
    // call forces it open so activity isn't hidden.
    expect(container.querySelectorAll('.nbi-tool-call')).toHaveLength(5);
  });

  it('surfaces a failed count in the summary', () => {
    const mixed = [
      { id: 'a', title: 'A', kind: 'read', status: 'completed' },
      { id: 'b', title: 'B', kind: 'read', status: 'completed' },
      { id: 'c', title: 'C', kind: 'edit', status: 'failed' }
    ];
    render(<ToolCallGroup toolCalls={mixed} />);
    expect(screen.getByText('3 tool calls (1 failed)')).toBeInTheDocument();
  });
});
