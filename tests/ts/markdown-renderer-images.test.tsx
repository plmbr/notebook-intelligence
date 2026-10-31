// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { MarkdownRenderer } from '../../src/markdown-renderer';

function markdownView(markdown: string, execute: jest.Mock) {
  return (
    <MarkdownRenderer
      getApp={() => ({ commands: { execute } }) as any}
      getActiveDocumentInfo={() =>
        ({ filename: 'work.ipynb', filePath: 'notebooks/work.ipynb' }) as any
      }
    >
      {markdown}
    </MarkdownRenderer>
  );
}

function renderMarkdown(markdown: string) {
  const execute = jest.fn().mockResolvedValue(undefined);
  return { execute, ...render(markdownView(markdown, execute)) };
}

// Keep the real react-markdown parser and plugins in this suite. Testing only
// MarkdownImage would miss accidentally removing its renderer override.
describe('MarkdownRenderer image handling', () => {
  const remoteImage = 'https://example.test/collect?imageSecret=demo';

  it.each([
    ['HTTPS', `![chart](${remoteImage})`],
    ['HTTP', '![chart](http://example.test/collect?imageSecret=demo)'],
    ['protocol-relative', '![chart](//example.test/collect?imageSecret=demo)'],
    ['same-origin', '![chart](/collect?imageSecret=demo)'],
    ['workspace-relative', '![chart](../collect?imageSecret=demo)'],
    ['data', '![chart](data:image/png;base64,aW1hZ2VTZWNyZXQ=)'],
    ['fragment', '![chart](#imageSecret)'],
    ['empty destination', '![chart]()'],
    ['reference', `![chart][image]\n\n[image]: ${remoteImage}`],
    ['collapsed reference', `![chart][]\n\n[chart]: ${remoteImage}`],
    ['shortcut reference', `![chart]\n\n[chart]: ${remoteImage}`],
    ['title', `![chart](${remoteImage} "imageSecret title")`],
    ['linked', `[![chart](${remoteImage})](https://example.test/docs)`],
    ['GFM table', `| chart |\n| --- |\n| ![chart](${remoteImage}) |`]
  ])(
    'renders a %s image as visible text without its destination',
    (_name, markdown) => {
      const { container, execute } = renderMarkdown(markdown);
      expect(screen.getByText('[Image blocked: chart]')).toBeVisible();
      expect(
        container.querySelector('img, [src], [srcset], [poster]')
      ).toBeNull();
      expect(container.innerHTML).not.toContain('imageSecret');
      expect(container.innerHTML).not.toContain('data:image');
      expect(execute).not.toHaveBeenCalled();
    }
  );

  it('keeps the outer link of a linked image usable without exposing its image URL', () => {
    const { container } = renderMarkdown(
      `[![chart](${remoteImage})](https://example.test/docs)`
    );
    const link = screen.getByRole('link', { name: /Image blocked: chart/ });
    expect(link).toHaveAttribute('href', 'https://example.test/docs');
    expect(link).toHaveAttribute('target', '_blank');
    expect(container.innerHTML).not.toContain('imageSecret');
  });

  it('renders a visible fallback when an image has no description', () => {
    const { container } = renderMarkdown(`![](${remoteImage})`);
    const notice = screen.getByText('[Image blocked]');
    expect(notice).toBeVisible();
    expect(notice).not.toHaveClass('nbi-sr-only');
    expect(container.innerHTML).not.toContain('imageSecret');
  });

  it('preserves a joined emoji description through Markdown parsing', () => {
    renderMarkdown(`![Developer 👩\u200d💻](${remoteImage})`);
    expect(
      screen.getByText('[Image blocked: Developer 👩\u200d💻]')
    ).toBeVisible();
  });

  it('keeps raw image and media HTML as inert literal text', () => {
    const { container } = renderMarkdown(
      '<img src="https://example.test/image">\n\n' +
        '<video poster="https://example.test/poster" src="https://example.test/video"></video>\n\n' +
        '<picture><source srcset="https://example.test/source"></picture>'
    );
    expect(
      container.querySelector(
        'img, video, picture, source, [src], [srcset], [poster]'
      )
    ).toBeNull();
    expect(container.textContent).toContain(
      '<img src="https://example.test/image">'
    );
  });

  it('never creates an image as a streamed Markdown image arrives', () => {
    const markdown = `![chart](${remoteImage})`;
    const { container, execute, rerender } = renderMarkdown('');
    for (let end = 0; end <= markdown.length; end++) {
      rerender(markdownView(markdown.slice(0, end), execute));
      expect(
        container.querySelector('img, [src], [srcset], [poster]')
      ).toBeNull();
    }
    expect(screen.getByText('[Image blocked: chart]')).toBeVisible();
    expect(container.innerHTML).not.toContain('imageSecret');
  });

  it('preserves ordinary links, literal code and notebook code actions', () => {
    const { container, execute } = renderMarkdown(
      '[README](README.md) and [docs](https://example.test/docs)\n\n' +
        '`![literal](https://example.test/code)`\n\n' +
        '```python\nprint(1)\n```'
    );
    fireEvent.click(screen.getByRole('link', { name: 'README' }));
    expect(execute).toHaveBeenCalledWith('docmanager:open', {
      path: 'notebooks/README.md'
    });
    expect(screen.getByRole('link', { name: /docs/ })).toHaveAttribute(
      'target',
      '_blank'
    );
    expect(container.querySelector('code')?.textContent).toBe(
      '![literal](https://example.test/code)'
    );
    for (const [name, command] of [
      ['Add code as new cell', 'add-code-as-new-cell'],
      ['Insert code at cursor', 'insert-at-cursor'],
      ['Create new file from code', 'create-new-file'],
      ['Create new notebook from code', 'create-new-notebook']
    ]) {
      fireEvent.click(screen.getByRole('button', { name }));
      expect(execute).toHaveBeenCalledWith(`notebook-intelligence:${command}`, {
        language: 'python',
        code: 'print(1)'
      });
    }
  });
});
