// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { render, screen } from '@testing-library/react';

import { ConfirmationDetails } from '../../src/components/confirmation-details';

function mockBoxSize(
  scrollHeight: number,
  clientHeight: number,
  scrollWidth = 100,
  clientWidth = 100
) {
  const spies = [
    jest
      .spyOn(HTMLElement.prototype, 'scrollHeight', 'get')
      .mockReturnValue(scrollHeight),
    jest
      .spyOn(HTMLElement.prototype, 'clientHeight', 'get')
      .mockReturnValue(clientHeight),
    jest
      .spyOn(HTMLElement.prototype, 'scrollWidth', 'get')
      .mockReturnValue(scrollWidth),
    jest
      .spyOn(HTMLElement.prototype, 'clientWidth', 'get')
      .mockReturnValue(clientWidth)
  ];
  return () => spies.forEach(spy => spy.mockRestore());
}

describe('ConfirmationDetails', () => {
  it('renders each label with its value as plain text', () => {
    render(
      <ConfirmationDetails
        details={[
          { label: 'Command (run by zsh -lc)', value: '<b>ls</b> -la' },
          { label: 'Working directory', value: '/work' }
        ]}
      />
    );
    expect(screen.getByText('Command (run by zsh -lc)').tagName).toBe('DT');
    expect(screen.getByText('<b>ls</b> -la').tagName).toBe('PRE');
    expect(screen.getByText('/work')).toHaveAttribute('tabindex', '0');
  });

  it('renders nothing for missing or malformed details', () => {
    const { container, rerender } = render(
      <ConfirmationDetails details={undefined} />
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<ConfirmationDetails details="text" />);
    expect(container).toBeEmptyDOMElement();
    rerender(
      <ConfirmationDetails details={[{ label: 'Args', value: { a: 1 } }]} />
    );
    expect(screen.getByText('[object Object]').tagName).toBe('PRE');
  });

  it('says so when a value is clipped by its block', () => {
    const restore = mockBoxSize(400, 160);
    try {
      render(
        <ConfirmationDetails details={[{ label: 'Command', value: 'ls' }]} />
      );
      expect(
        screen.getByText('Scroll to see all of this value.')
      ).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('says so when a value overflows sideways', () => {
    const restore = mockBoxSize(40, 40, 900, 176);
    try {
      render(
        <ConfirmationDetails details={[{ label: 'Command', value: 'ls' }]} />
      );
      expect(
        screen.getByText('Scroll to see all of this value.')
      ).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('adds no note when the value fits', () => {
    const restore = mockBoxSize(40, 40);
    try {
      render(
        <ConfirmationDetails details={[{ label: 'Command', value: 'ls' }]} />
      );
      expect(
        screen.queryByText('Scroll to see all of this value.')
      ).not.toBeInTheDocument();
    } finally {
      restore();
    }
  });
});
