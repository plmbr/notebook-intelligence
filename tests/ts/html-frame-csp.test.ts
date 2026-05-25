// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import { HTML_FRAME_CSP, injectHtmlFrameCsp } from '../../src/html-frame-csp';

describe('HTML_FRAME_CSP', () => {
  it('disables network egress by default', () => {
    expect(HTML_FRAME_CSP).toContain("default-src 'none'");
    expect(HTML_FRAME_CSP).toContain("connect-src 'none'");
    expect(HTML_FRAME_CSP).toContain("frame-src 'none'");
    expect(HTML_FRAME_CSP).toContain("object-src 'none'");
  });

  it('allows inline scripts and styles so self-contained tool HTML renders', () => {
    expect(HTML_FRAME_CSP).toContain("script-src 'unsafe-inline'");
    expect(HTML_FRAME_CSP).toContain("style-src 'unsafe-inline'");
  });

  it('only permits data: images and fonts', () => {
    expect(HTML_FRAME_CSP).toContain('img-src data:');
    expect(HTML_FRAME_CSP).toContain('font-src data:');
  });

  it('blocks base-uri and form-action escape hatches', () => {
    expect(HTML_FRAME_CSP).toContain("base-uri 'none'");
    expect(HTML_FRAME_CSP).toContain("form-action 'none'");
  });

  it('explicitly blocks worker / child / manifest / media sinks', () => {
    expect(HTML_FRAME_CSP).toContain("worker-src 'none'");
    expect(HTML_FRAME_CSP).toContain("child-src 'none'");
    expect(HTML_FRAME_CSP).toContain("manifest-src 'none'");
    expect(HTML_FRAME_CSP).toContain("media-src 'none'");
  });
});

describe('injectHtmlFrameCsp', () => {
  const META_RE =
    /^<meta http-equiv="Content-Security-Policy" content="[^"]+">/;

  it('always prepends the CSP meta so it sees the document first', () => {
    expect(injectHtmlFrameCsp('<p>hi</p>')).toMatch(META_RE);
    expect(injectHtmlFrameCsp('<p>hi</p>')).toContain('<p>hi</p>');
  });

  it('prepends even when the source opens its own <head>', () => {
    // Author-supplied <head> must not get the meta inserted "inside" it
    // by a regex that could be fooled by <head> in a comment or
    // <noscript>. Prepending puts the meta before any author-controlled
    // bytes; the browser tokenizer wraps it in a synthetic <head> ahead
    // of the author's opening <head>.
    const src = '<html><head><title>x</title></head><body>y</body></html>';
    expect(injectHtmlFrameCsp(src)).toMatch(META_RE);
  });

  it('keeps a leading DOCTYPE at position zero and slots the meta after it', () => {
    // A doctype declaration must be the very first content in the
    // document; putting the CSP meta ahead of it would put the iframe
    // in quirks mode, which breaks the CSS that matplotlib / plotly
    // emit. Splice the meta in immediately after the doctype.
    const src = '<!DOCTYPE html><html><head></head><body>y</body></html>';
    const out = injectHtmlFrameCsp(src);
    expect(out.startsWith('<!DOCTYPE html>')).toBe(true);
    expect(out.indexOf('<!DOCTYPE')).toBeLessThan(out.indexOf('<meta'));
    expect(out.indexOf('<meta')).toBeLessThan(out.indexOf('<html'));
  });

  it('handles BOM + leading whitespace before the doctype', () => {
    const src = '﻿  <!doctype HTML><html><body>y</body></html>';
    const out = injectHtmlFrameCsp(src);
    // The doctype is still at the start of the document (after the
    // BOM/whitespace prefix); the meta is spliced in right after it.
    const doctypeIdx = out.toLowerCase().indexOf('<!doctype');
    const metaIdx = out.indexOf('<meta');
    expect(doctypeIdx).toBeGreaterThanOrEqual(0);
    expect(metaIdx).toBeGreaterThan(doctypeIdx);
    expect(metaIdx).toBeLessThan(out.indexOf('<html'));
  });

  it('does not treat a comment-disguised doctype as a real doctype', () => {
    // <!-- <!DOCTYPE html> --> is a comment, not a doctype. The browser
    // ignores it for quirks-mode purposes, and our regex must too.
    const src = '<!-- <!DOCTYPE html> --><html><body>y</body></html>';
    const out = injectHtmlFrameCsp(src);
    // No doctype detected, so the meta goes at position zero.
    expect(out.startsWith('<meta')).toBe(true);
  });

  it('is unaffected by <head> hiding in a comment', () => {
    // The pre-fix regex strategy could be confused by this construction.
    // Pin the always-prepend behavior so a future refactor cannot
    // re-introduce that gap.
    const src = '<!--<head>--><head><script>x</script></head>';
    const out = injectHtmlFrameCsp(src);
    expect(out).toMatch(META_RE);
    expect(out.indexOf('<meta')).toBeLessThan(out.indexOf('<!--'));
  });

  it('places the meta before any <script> in the document', () => {
    const src = '<html><body><script>alert(1)</script></body></html>';
    const out = injectHtmlFrameCsp(src);
    const metaIdx = out.indexOf('<meta');
    const scriptIdx = out.indexOf('<script');
    expect(metaIdx).toBeGreaterThanOrEqual(0);
    expect(scriptIdx).toBeGreaterThan(metaIdx);
  });

  it('does not deduplicate when called twice (idempotency caveat)', () => {
    // Two metas are harmless: per CSP spec the strictest policy wins.
    // Pin this so a future caller does not quietly accumulate metas in
    // an unexpected configuration.
    const first = injectHtmlFrameCsp('<p>x</p>');
    const second = injectHtmlFrameCsp(first);
    const count = (second.match(/Content-Security-Policy/g) || []).length;
    expect(count).toBe(2);
  });

  it('returns the bare meta when source is empty or nullish', () => {
    expect(injectHtmlFrameCsp('')).toMatch(META_RE);
    expect(injectHtmlFrameCsp(null)).toMatch(META_RE);
    expect(injectHtmlFrameCsp(undefined)).toMatch(META_RE);
  });
});
