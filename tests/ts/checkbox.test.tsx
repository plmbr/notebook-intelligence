// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { CheckBoxItem } from '../../src/components/checkbox';

describe('CheckBoxItem', () => {
  it('exposes role=checkbox with the current aria-checked state', () => {
    const onClick = jest.fn();
    const { rerender } = render(
      <CheckBoxItem label="On" checked={false} onClick={onClick} />
    );
    expect(screen.getByRole('checkbox')).toHaveAttribute(
      'aria-checked',
      'false'
    );
    rerender(<CheckBoxItem label="On" checked={true} onClick={onClick} />);
    expect(screen.getByRole('checkbox')).toHaveAttribute(
      'aria-checked',
      'true'
    );
  });

  it('toggles on Space and Enter when focused', () => {
    const onClick = jest.fn();
    render(<CheckBoxItem label="Test" checked={false} onClick={onClick} />);
    const checkbox = screen.getByRole('checkbox');
    checkbox.focus();
    expect(checkbox).toHaveFocus();
    fireEvent.keyDown(checkbox, { key: ' ' });
    fireEvent.keyDown(checkbox, { key: 'Enter' });
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it('still toggles on mouse click for sighted users', () => {
    const onClick = jest.fn();
    render(<CheckBoxItem label="Click" checked={false} onClick={onClick} />);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('marks itself aria-disabled and ignores activation when disabled', () => {
    const onClick = jest.fn();
    render(
      <CheckBoxItem
        label="Off"
        checked={false}
        disabled={true}
        onClick={onClick}
      />
    );
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(checkbox);
    fireEvent.keyDown(checkbox, { key: ' ' });
    expect(onClick).not.toHaveBeenCalled();
  });

  it('is focusable when enabled and unfocusable when disabled', () => {
    const onClick = jest.fn();
    const { rerender } = render(
      <CheckBoxItem label="X" checked={false} onClick={onClick} />
    );
    expect(screen.getByRole('checkbox')).toHaveAttribute('tabindex', '0');
    rerender(
      <CheckBoxItem
        label="X"
        checked={false}
        disabled={true}
        onClick={onClick}
      />
    );
    expect(screen.getByRole('checkbox')).toHaveAttribute('tabindex', '-1');
  });
});
