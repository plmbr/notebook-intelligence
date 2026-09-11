// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React, { useEffect, useRef, useState } from 'react';

// One agent-supplied value in its own bounded, scrollable block. When the
// block clips its content, a note outside the block says so: rendered text
// can be taller than its label's line and character counts suggest (wide
// glyphs, tabs), and overlay scrollbars stay hidden until scrolled.
function ConfirmationDetailValue(props: { value: string }): JSX.Element {
  const ref = useRef<HTMLPreElement>(null);
  const [clipped, setClipped] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }
    const measure = () => {
      setClipped(
        element.scrollHeight > element.clientHeight + 1 ||
          element.scrollWidth > element.clientWidth + 1
      );
    };
    measure();
    if (typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [props.value]);

  return (
    <dd>
      <pre ref={ref} tabIndex={0}>
        {props.value}
      </pre>
      {clipped ? (
        <div className="chat-confirmation-detail-clipped">
          Scroll to see all of this value.
        </div>
      ) : null}
    </dd>
  );
}

// Label and value pairs shown on a confirmation card. Labels come from NBI;
// values may come from an agent and are rendered as plain text.
export function ConfirmationDetails(props: { details: unknown }): JSX.Element {
  if (!Array.isArray(props.details) || props.details.length === 0) {
    return null;
  }
  return (
    <dl className="chat-confirmation-details">
      {props.details.map((detail: any, index: number) => (
        <div className="chat-confirmation-detail" key={index}>
          <dt>{String(detail?.label ?? '')}</dt>
          <ConfirmationDetailValue value={String(detail?.value ?? '')} />
        </div>
      ))}
    </dl>
  );
}
