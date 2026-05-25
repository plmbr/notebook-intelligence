// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

/**
 * Content-Security-Policy injected into every HTMLFrame blob document.
 *
 * The iframe already runs with sandbox="allow-scripts" (no allow-same-origin),
 * so cookies and parent DOM are unreachable. But scripts in a null-origin
 * context can still fetch() to any URL the user's browser can reach:
 * cluster intranet, 169.254.169.254 cloud metadata, the Jupyter server
 * itself. Inline scripts/styles stay enabled because most LLM/tool HTML
 * output (matplotlib, plotly, custom dashboards) is self-contained inline;
 * external CDN loads and any network egress are blocked. img/font are
 * allowed only as data: URIs so inline visualizations still render.
 */
export const HTML_FRAME_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  'img-src data:',
  'font-src data:',
  "connect-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-src 'none'",
  "child-src 'none'",
  "worker-src 'none'",
  "manifest-src 'none'",
  "media-src 'none'",
  "object-src 'none'"
].join('; ');

const CSP_META_TAG = `<meta http-equiv="Content-Security-Policy" content="${HTML_FRAME_CSP}">`;

// `<!DOCTYPE html>` or any other doctype declaration MUST be the very
// first thing in the document or the parser drops into quirks mode,
// which breaks CSS that matplotlib/plotly emit (and disables a handful
// of CSP enforcement details in older WebKit). Detect a leading doctype
// (allowing for an optional BOM and leading whitespace) and slot the
// meta right after it instead of before it.
const DOCTYPE_RE = /^(?:\ufeff)?\s*<!DOCTYPE\b[^>]*>/i;

/**
 * Prepend the CSP `<meta>` tag to untrusted HTML so the resulting blob
 * document boots under policy.
 *
 * Almost-always prepend rather than trying to locate `<head>`: an
 * HTML-naive regex can be fooled by `<head>` inside a comment,
 * `<noscript>`, `<textarea>`, or a `<![CDATA[ ]]>` block, which would
 * let the actual `<head>` parsed by the browser run unguarded.
 * Prepending puts the meta before everything; the browser's tokenizer
 * folds a leading meta into the synthetic `<head>` it builds, ahead of
 * any author-supplied `<head>` opening tag.
 *
 * The one exception is a leading `<!DOCTYPE>` declaration: the doctype
 * has to remain at position zero or the document parses in quirks mode,
 * so we splice the meta in immediately AFTER the doctype rather than
 * before it. A comment-disguised doctype (`<!-- <!DOCTYPE html> -->`)
 * is not a real doctype and the regex skips it, which is fine because
 * the browser also ignores comment-wrapped doctypes.
 */
export function injectHtmlFrameCsp(source: string | null | undefined): string {
  if (!source) {
    return CSP_META_TAG;
  }
  const match = DOCTYPE_RE.exec(source);
  if (match) {
    const idx = match.index + match[0].length;
    return source.slice(0, idx) + CSP_META_TAG + source.slice(idx);
  }
  return CSP_META_TAG + source;
}
