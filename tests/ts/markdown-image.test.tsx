// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { MarkdownImage } from '../../src/components/markdown-image';
import { TranslationContext } from '../../src/i18n';
import { pseudo, pseudoBundle } from './pseudo-translator';

describe('MarkdownImage', () => {
  it.each([
    ['ordinary description', 'A chart of sales'],
    ['non-Latin letters', '売上の推移'],
    ['right-to-left letters', 'رسم بياني'],
    ['non-breaking space', 'Sales\u00a0chart'],
    ['zero-width non-joiner', 'می\u200cروم'],
    ['joined emoji', 'Developer 👩\u200d💻']
  ])('keeps %s in the visible notice', (_name, alt) => {
    render(<MarkdownImage alt={alt} />);
    const notice = screen.getByText(`[Image blocked: ${alt}]`, {
      normalizer: text => text
    });
    expect(notice).toBeVisible();
    expect(notice).not.toHaveClass('nbi-sr-only');
    expect(notice.closest('.nbi-sr-only, [aria-hidden="true"]')).toBeNull();
  });

  it.each([undefined, null, 0, false, {}, '', ' ', '\u00a0'])(
    'shows a visible fallback for a missing or unusable description (%j)',
    alt => {
      render(<MarkdownImage alt={alt} />);
      const notice = screen.getByText('[Image blocked]');
      expect(notice).toBeVisible();
      expect(notice).not.toHaveClass('nbi-sr-only');
      expect(notice.closest('.nbi-sr-only, [aria-hidden="true"]')).toBeNull();
    }
  );

  it.each([
    ['NUL', '\u0000'],
    ['tab', '\u0009'],
    ['newline', '\u000a'],
    ['carriage return', '\u000d'],
    ['escape', '\u001b'],
    ['DEL', '\u007f'],
    ['C1 control', '\u0085'],
    ['Arabic letter mark', '\u061c'],
    ['left-to-right mark', '\u200e'],
    ['right-to-left mark', '\u200f'],
    ['left-to-right embedding', '\u202a'],
    ['right-to-left embedding', '\u202b'],
    ['pop directional formatting', '\u202c'],
    ['left-to-right override', '\u202d'],
    ['right-to-left override', '\u202e'],
    ['left-to-right isolate', '\u2066'],
    ['right-to-left isolate', '\u2067'],
    ['first strong isolate', '\u2068'],
    ['pop directional isolate', '\u2069']
  ])('uses the fallback for a description containing %s', (_name, control) => {
    const { container } = render(<MarkdownImage alt={`chart${control}name`} />);
    expect(screen.getByText('[Image blocked]')).toBeVisible();
    expect(container.textContent).not.toContain('chart');
    expect(container.textContent).not.toContain(control);
  });

  it('does not forward image attributes or unexpected runtime props', () => {
    const props = {
      alt: 'Chart',
      src: 'https://example.test/collect?secret=image',
      srcSet: 'https://example.test/collect?secret=srcset 2x',
      poster: 'https://example.test/collect?secret=poster',
      title: 'https://example.test/collect?secret=title',
      style: {
        backgroundImage: 'url(https://example.test/collect?secret=style)'
      },
      onClick: jest.fn(),
      dangerouslySetInnerHTML: { __html: '<img src="/runtime-secret">' }
    };
    const { container } = render(<MarkdownImage {...props} />);
    expect(screen.getByText('[Image blocked: Chart]')).toBeVisible();
    expect(
      container.querySelector(
        'img, [src], [srcset], [poster], [title], [style]'
      )
    ).toBeNull();
    expect(container.innerHTML).not.toContain('secret');
    fireEvent.click(screen.getByText('[Image blocked: Chart]'));
    expect(props.onClick).not.toHaveBeenCalled();
  });

  it('escapes an HTML-looking description as text', () => {
    const alt = '<img src="/inert"> & <script>alert(1)</script>';
    const { container } = render(<MarkdownImage alt={alt} />);
    expect(screen.getByText(`[Image blocked: ${alt}]`)).toBeVisible();
    expect(container.querySelector('img, script, [src]')).toBeNull();
  });

  it.each(['Chart', ''])('translates the notice with alt %j', alt => {
    render(
      <TranslationContext.Provider value={pseudoBundle}>
        <MarkdownImage alt={alt} />
      </TranslationContext.Provider>
    );
    const notice = alt ? `[Image blocked: ${alt}]` : '[Image blocked]';
    expect(screen.getByText(pseudo(notice))).toBeVisible();
    expect(screen.queryByText(notice)).toBeNull();
  });
});
