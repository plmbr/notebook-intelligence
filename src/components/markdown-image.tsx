// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { useTrans } from '../i18n';
import { isControlOrBidiCodepoint } from '../text-codepoints';

type MarkdownImageProps = {
  alt?: unknown;
};

/**
 * Chat Markdown images must not fetch model-selected URLs automatically.
 * Render a visible notice instead, without forwarding any image attributes.
 * This blocks local and remote Markdown images; dedicated image response
 * events and notebook Markdown use separate renderers.
 */
export function MarkdownImage({ alt }: MarkdownImageProps): React.ReactElement {
  const trans = useTrans();
  // Reject controls that can disguise the notice, while retaining ordinary
  // Unicode text, nonbreaking spaces, and joiners used in scripts and emoji.
  const safeAlt =
    typeof alt === 'string' &&
    alt.trim() !== '' &&
    !Array.from(alt).some(char => {
      const code = char.codePointAt(0)!;
      return (
        isControlOrBidiCodepoint(code) ||
        code === 0x061c ||
        code === 0x200e ||
        code === 0x200f
      );
    })
      ? alt
      : undefined;
  return (
    <span className="nbi-blocked-image" dir="auto">
      {safeAlt
        ? trans.__('[Image blocked: %1]', safeAlt)
        : trans.__('[Image blocked]')}
    </span>
  );
}
