// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { Prism as SyntaxHighlighterBase } from 'react-syntax-highlighter';
const SyntaxHighlighter =
  SyntaxHighlighterBase as unknown as React.ComponentType<any>;
import {
  oneLight,
  oneDark
} from 'react-syntax-highlighter/dist/cjs/styles/prism';
import { VscNewFile, VscInsert, VscCopy, VscNotebook, VscAdd } from './icons';
import { JupyterFrontEnd } from '@jupyterlab/application';
import { PathExt } from '@jupyterlab/coreutils';
import { MarkdownImage } from './components/markdown-image';
import { MarkdownLink } from './components/markdown-link';
import { isDarkTheme, writeTextToClipboard } from './utils';
import { IActiveDocumentInfo } from './tokens';
import { resolveCodeClassName } from './markdown-code-class';
import { useTrans } from './i18n';

// Block elements take their direction from their own text (dir="auto"), so
// an English paragraph, list or table reads left to right in an Arabic reply
// and the reverse, bullets, columns and borders included. Code stays left to
// right (style/base.css).
const AUTO_DIRECTION_BLOCKS = [
  'p',
  'ul',
  'ol',
  'table',
  'blockquote',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6'
] as const;
const autoDirectionComponents = Object.fromEntries(
  AUTO_DIRECTION_BLOCKS.map(tag => [
    tag,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    ({ node, ...props }: any) =>
      React.createElement(tag, { ...props, dir: 'auto' })
  ])
);

type MarkdownRendererProps = {
  children: string;
  getApp: () => JupyterFrontEnd;
  getActiveDocumentInfo(): IActiveDocumentInfo;
};

export function MarkdownRenderer({
  children: markdown,
  getApp,
  getActiveDocumentInfo
}: MarkdownRendererProps) {
  const trans = useTrans();
  const app = getApp();
  const activeDocumentInfo = getActiveDocumentInfo();
  const isNotebook = activeDocumentInfo.filename.endsWith('.ipynb');
  // Resolve workspace-relative LLM links against the active document's
  // directory so `[file](README.md)` from a chat scoped to
  // `notebooks/proj/work.ipynb` lands at `notebooks/proj/README.md` (the
  // user's mental model) rather than the server-root README.
  const linkBaseDir = activeDocumentInfo.filePath
    ? PathExt.dirname(activeDocumentInfo.filePath)
    : '';

  return (
    // No `rehype-raw` plugin: raw HTML in chat markdown (e.g. an LLM
    // emitting `<a href="javascript:...">`) renders as literal text, not
    // a DOM anchor, so the only anchor sink is the CommonMark/GFM `a`
    // node handled by `SafeAnchor` below. Any future change that enables
    // raw HTML needs to add a rehype-sanitize pass alongside.
    <Markdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      components={{
        ...autoDirectionComponents,
        // CommonMark `<https://...>` autolinks, `[text](url)`, and
        // reference-style links all normalize to the same `a` node.
        // `MarkdownLink` routes fragment-only and workspace-relative
        // hrefs through Lab's docmanager so an LLM-emitted link can't
        // replace the JupyterLab shell, and hands everything else to
        // SafeAnchor for the `_blank` + scheme-allowlist treatment.
        a: ({ href, title, children }: any) => (
          <MarkdownLink
            app={app}
            baseDir={linkBaseDir}
            href={href}
            title={title}
          >
            {children}
          </MarkdownLink>
        ),
        // CommonMark `![alt](url)` and reference-style images normalize to
        // the same `img` node. Unlike an anchor it needs no click: the
        // browser fetches `src` as soon as the node renders, so a model
        // steered by injected content could stream out an image URL that
        // carries chat/workspace context in its query string. `MarkdownImage`
        // keeps `src` out of the DOM entirely.
        img: ({ alt }: any) => <MarkdownImage alt={alt} />,
        code({ node, inline, className, children, getApp, ...props }: any) {
          const match = /language-(\w+)/.exec(className || '');
          const codeString =
            children === null || children === undefined
              ? ''
              : String(children).replace(/\n$/, '');
          const language = match ? match[1] : 'text';

          const handleCopyClick = () => {
            void writeTextToClipboard(codeString);
          };

          const handleInsertAtCursorClick = () => {
            app.commands.execute('notebook-intelligence:insert-at-cursor', {
              language,
              code: codeString
            });
          };

          const handleAddCodeAsNewCell = () => {
            app.commands.execute('notebook-intelligence:add-code-as-new-cell', {
              language,
              code: codeString
            });
          };

          const handleCreateNewFileClick = () => {
            app.commands.execute('notebook-intelligence:create-new-file', {
              language,
              code: codeString
            });
          };

          const handleCreateNewNotebookClick = () => {
            app.commands.execute('notebook-intelligence:create-new-notebook', {
              language,
              code: codeString
            });
          };

          if (inline || !match) {
            return (
              <code
                className={resolveCodeClassName(children, className)}
                {...props}
              >
                {children}
              </code>
            );
          }
          return (
            <div>
              <div className="code-block-header">
                <div className="code-block-header-language">
                  <span>{language}</span>
                </div>
                {codeString !== '' && (
                  <>
                    <button
                      type="button"
                      className="code-block-header-button"
                      onClick={() => handleCopyClick()}
                      aria-label={trans.__('Copy code to clipboard')}
                    >
                      <VscCopy size={16} aria-hidden="true" />
                      <span>{trans.__('Copy')}</span>
                    </button>
                    <button
                      type="button"
                      className="code-block-header-button"
                      onClick={() => handleInsertAtCursorClick()}
                      aria-label={trans.__('Insert code at cursor')}
                      title={trans.__('Insert at cursor')}
                    >
                      <VscInsert size={16} aria-hidden="true" />
                    </button>
                    {isNotebook && (
                      <button
                        type="button"
                        className="code-block-header-button"
                        onClick={() => handleAddCodeAsNewCell()}
                        aria-label={trans.__('Add code as new cell')}
                        title={trans.__('Add as new cell')}
                      >
                        <VscAdd size={16} aria-hidden="true" />
                      </button>
                    )}
                    <button
                      type="button"
                      className="code-block-header-button"
                      onClick={() => handleCreateNewFileClick()}
                      aria-label={trans.__('Create new file from code')}
                      title={trans.__('New file')}
                    >
                      <VscNewFile size={16} aria-hidden="true" />
                    </button>
                    {language === 'python' && (
                      <button
                        type="button"
                        className="code-block-header-button"
                        onClick={() => handleCreateNewNotebookClick()}
                        aria-label={trans.__('Create new notebook from code')}
                        title={trans.__('New notebook')}
                      >
                        <VscNotebook size={16} aria-hidden="true" />
                      </button>
                    )}
                  </>
                )}
              </div>
              <SyntaxHighlighter
                style={isDarkTheme() ? oneDark : oneLight}
                PreTag="div"
                language={language}
                {...props}
              >
                {codeString}
              </SyntaxHighlighter>
            </div>
          );
        }
      }}
    >
      {markdown}
    </Markdown>
  );
}
