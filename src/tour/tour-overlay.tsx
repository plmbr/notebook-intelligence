// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React, {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import { createPortal } from 'react-dom';

import {
  TourPlacement,
  IResolvedTourStep,
  activeTourSteps
} from './tour-steps';
import { markTourCompleted } from './tour-state';
import { NBIAPI } from '../api';
import { uiLabel } from './tour-config';

const TOOLTIP_GAP_PX = 12;
const TOOLTIP_WIDTH_PX = 320;
// Fallback used on the first render before the tooltip is measured.
// Chosen to be larger than the typical rendered height so the initial
// clamp errs toward staying on-screen rather than overshooting.
const TOOLTIP_HEIGHT_FALLBACK_PX = 200;

/**
 * Compute the on-screen position of the tooltip given the anchor's
 * bounding rect, the requested placement, and the tooltip's measured
 * height. The clamp keeps the box fully on-screen even when the anchor
 * sits near a viewport edge.
 *
 * Placement semantics: 'top' puts the tooltip above the anchor (its
 * bottom edge gap-px above anchor.top), 'bottom' puts it below, 'left'
 * to the left, 'right' to the right. The previous version omitted
 * tooltip width/height from the top/left placements, which let the box
 * overlap the anchor instead of sitting outside it.
 */
function computeTooltipPosition(
  anchorRect: DOMRect,
  placement: Exclude<TourPlacement, 'center'>,
  tooltipHeight: number
): { top: number; left: number } {
  let top = 0;
  let left = 0;
  switch (placement) {
    case 'top':
      top = anchorRect.top - TOOLTIP_GAP_PX - tooltipHeight;
      left = anchorRect.left + anchorRect.width / 2 - TOOLTIP_WIDTH_PX / 2;
      break;
    case 'bottom':
      top = anchorRect.bottom + TOOLTIP_GAP_PX;
      left = anchorRect.left + anchorRect.width / 2 - TOOLTIP_WIDTH_PX / 2;
      break;
    case 'left':
      top = anchorRect.top + anchorRect.height / 2 - tooltipHeight / 2;
      left = anchorRect.left - TOOLTIP_GAP_PX - TOOLTIP_WIDTH_PX;
      break;
    case 'right':
      top = anchorRect.top + anchorRect.height / 2 - tooltipHeight / 2;
      left = anchorRect.right + TOOLTIP_GAP_PX;
      break;
  }
  // Clamp inside the viewport with an 8px margin so the tooltip never
  // disappears off-screen near the edges. The vertical clamp accounts
  // for tooltip height so the bottom edge stays visible even when the
  // anchor is near the bottom of the viewport.
  const margin = 8;
  left = Math.max(
    margin,
    Math.min(left, window.innerWidth - TOOLTIP_WIDTH_PX - margin)
  );
  top = Math.max(
    margin,
    Math.min(top, window.innerHeight - tooltipHeight - margin)
  );
  return { top, left };
}

function findAnchor(anchorId: string | null): HTMLElement | null {
  if (!anchorId) {
    return null;
  }
  return document.querySelector<HTMLElement>(`[data-tour-id="${anchorId}"]`);
}

interface ITourOverlayProps {
  // Render-control hooks. The parent owns the visibility decision so
  // the overlay stays a pure presentation component.
  onClose: () => void;
}

export function TourOverlay(props: ITourOverlayProps): JSX.Element | null {
  // Compute the list of steps once. Capabilities can change at runtime
  // (e.g. user switches Claude mode mid-tour) but recomputing the list
  // mid-flight would change indices under the user; freeze on mount.
  const steps = useMemo<IResolvedTourStep[]>(() => activeTourSteps(), []);
  // Freeze the admin overrides snapshot at mount, alongside `steps`, so
  // a config push mid-tour doesn't relabel the active overlay's buttons.
  const labels = useMemo(() => {
    const overrides = NBIAPI.config.tourOverrides;
    return {
      skip: uiLabel(overrides, 'skip', 'Skip tour'),
      next: uiLabel(overrides, 'next', 'Next'),
      back: uiLabel(overrides, 'back', 'Back'),
      done: uiLabel(overrides, 'done', 'Done')
    };
  }, []);
  const [index, setIndex] = useState(0);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [tooltipHeight, setTooltipHeight] = useState<number>(
    TOOLTIP_HEIGHT_FALLBACK_PX
  );
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  const step = steps[index];

  // Save focus on mount, restore on unmount. Pairs with the focus trap
  // below so the tour leaves focus where it found it (e.g. the prompt
  // textarea) instead of dumping the user to document.body.
  useEffect(() => {
    previouslyFocusedRef.current =
      (document.activeElement as HTMLElement | null) ?? null;
    return () => {
      const prev = previouslyFocusedRef.current;
      if (prev && document.contains(prev) && typeof prev.focus === 'function') {
        prev.focus();
      }
    };
  }, []);

  // Measure the tooltip *before* paint so the next frame clamps its
  // position against the actual rendered height. useLayoutEffect (not
  // useEffect) prevents the user seeing a frame at the fallback height.
  // Re-measure only on step change so a no-op render doesn't pay the
  // getBoundingClientRect tax.
  useLayoutEffect(() => {
    if (!tooltipRef.current) {
      return;
    }
    const h = tooltipRef.current.getBoundingClientRect().height;
    if (h && Math.abs(h - tooltipHeight) > 0.5) {
      setTooltipHeight(h);
    }
    // tooltipHeight intentionally omitted from deps: this effect only
    // re-runs on step change and the > 0.5px guard already prevents
    // infinite loops if measurement converges.
  }, [step?.id, index]);

  // Resolve the anchor synchronously before the next paint. If the
  // anchor isn't in the DOM yet (parent React tree may not have
  // committed), retry across a handful of animation frames before
  // giving up; missing anchors auto-advance so the user doesn't land
  // on a blank step. useLayoutEffect on the synchronous path
  // eliminates the one-frame "wrong position" flash on step change.
  useLayoutEffect(() => {
    if (!step) {
      return;
    }
    if (!step.anchorId) {
      setAnchorRect(null);
      return;
    }
    // Clear the stale rect from the previous step immediately so a
    // late paint never shows the spotlight in the old position.
    setAnchorRect(null);

    let rafId = 0;
    let attempts = 0;
    const MAX_ATTEMPTS = 10;
    let removeListeners = () => {};

    const tryResolve = () => {
      const anchor = findAnchor(step.anchorId);
      if (anchor) {
        const updateRect = () => setAnchorRect(anchor.getBoundingClientRect());
        updateRect();
        window.addEventListener('resize', updateRect);
        window.addEventListener('scroll', updateRect, true);
        removeListeners = () => {
          window.removeEventListener('resize', updateRect);
          window.removeEventListener('scroll', updateRect, true);
        };
        return;
      }
      attempts += 1;
      if (attempts >= MAX_ATTEMPTS) {
        // Genuinely missing; auto-advance so the user doesn't land on a
        // blank step.
        setIndex(i => i + 1);
        return;
      }
      rafId = requestAnimationFrame(tryResolve);
    };
    // Attempt the first resolve synchronously so a happy path step
    // change paints in the right place on the very next frame.
    tryResolve();

    return () => {
      cancelAnimationFrame(rafId);
      removeListeners();
    };
  }, [step?.anchorId, index]);

  // Stable callback refs so the keydown handler can stay bound for the
  // overlay's lifetime without re-binding per step. Closing over `index`
  // directly would make the deps load-bearing in a non-obvious way.
  const advanceRef = useRef(() => {});
  const backRef = useRef(() => {});
  const finishRef = useRef(() => {});

  // Keyboard nav: Esc dismisses, Enter / Right advance, Left back.
  // Tab/Shift-Tab are trapped inside the dialog (paired with
  // aria-modal="true" so screen readers' modal semantics match reality).
  // Ignore key presses targeted at editable elements so the prompt
  // textarea's history-nav arrow keys still work if focus somehow
  // landed there before the tour mounted.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inEditable =
        !!target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable);
      // Tab/Shift-Tab focus trap is enforced even when target is an
      // editable element so focus can't escape the dialog through the
      // textarea below it.
      if (e.key === 'Tab') {
        const root = rootRef.current;
        if (!root) {
          return;
        }
        const focusables = Array.from(
          root.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          )
        ).filter(el => !el.hasAttribute('disabled'));
        if (focusables.length === 0) {
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement as HTMLElement | null;
        // If focus is outside the dialog entirely (e.g. clicked through
        // the scrim somehow), pull it back to the first focusable.
        if (!active || !root.contains(active)) {
          e.preventDefault();
          first.focus();
          return;
        }
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
        return;
      }
      if (inEditable) {
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        finishRef.current();
      } else if (e.key === 'ArrowRight' || e.key === 'Enter') {
        e.preventDefault();
        advanceRef.current();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        backRef.current();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // If we run out of steps (e.g. every anchor disappeared) close the
  // tour on the next tick rather than calling setState inside the
  // render below.
  useEffect(() => {
    if (!step) {
      finish();
    }
  }, [step]);

  const advance = () => {
    if (index >= steps.length - 1) {
      finish();
      return;
    }
    setIndex(i => i + 1);
  };

  const back = () => {
    if (index > 0) {
      setIndex(i => i - 1);
    }
  };

  const finish = () => {
    markTourCompleted();
    props.onClose();
  };

  // Refresh the callback refs every render so the keydown listener
  // (bound once) always reads the latest closures.
  advanceRef.current = advance;
  backRef.current = back;
  finishRef.current = finish;

  if (!step) {
    // No step to render right now. The cleanup effect above will fire
    // `finish()` on the next tick; in the meantime return null so
    // React doesn't see a setState inside this render path.
    return null;
  }

  const isCenter = step.placement === 'center' || !step.anchorId;
  // Anchored steps are "ready" once we have measured the anchor for
  // *this* step. While unmeasured we keep the dialog mounted but
  // visually hidden so the user doesn't see a flash at the centered
  // fallback position before the real position lands.
  const measured = isCenter || anchorRect !== null;
  const tooltipStyle: React.CSSProperties = isCenter
    ? {
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: TOOLTIP_WIDTH_PX
      }
    : (() => {
        // Fall back to a zero-size rect at the viewport center when the
        // anchor hasn't been measured yet. `DOMRect` is the standard
        // constructor in the browser; jsdom-only test environments
        // sometimes lack it, so build a plain object that satisfies
        // the fields `computeTooltipPosition` reads.
        const rect: DOMRect =
          anchorRect ??
          ({
            top: window.innerHeight / 2,
            left: window.innerWidth / 2,
            right: window.innerWidth / 2,
            bottom: window.innerHeight / 2,
            width: 0,
            height: 0,
            x: window.innerWidth / 2,
            y: window.innerHeight / 2,
            toJSON: () => ({})
          } as DOMRect);
        // step.placement is guaranteed not to be 'center' here (isCenter
        // would have been true otherwise); narrow for the type checker.
        const placement = step.placement as Exclude<TourPlacement, 'center'>;
        return {
          ...computeTooltipPosition(rect, placement, tooltipHeight),
          width: TOOLTIP_WIDTH_PX,
          visibility: measured ? ('visible' as const) : ('hidden' as const)
        };
      })();

  const spotlight = !isCenter && anchorRect && (
    <div
      className="nbi-tour-spotlight"
      style={{
        top: anchorRect.top - 4,
        left: anchorRect.left - 4,
        width: anchorRect.width + 8,
        height: anchorRect.height + 8
      }}
    />
  );

  const isLast = index === steps.length - 1;
  const progress = ((index + 1) / steps.length) * 100;

  // Render into document.body via portal so the overlay can extend
  // outside the sidebar's clip region and float over the rest of
  // JupyterLab.
  // ARIA: the dialog is modal-ish (covers the UI), so flag it as such.
  // The label / description IDs change per step, but most screen
  // readers don't re-announce when those attrs change without remount.
  // The step body is wrapped in an aria-live="polite" region so each
  // transition is announced as the content changes.
  const titleId = `nbi-tour-title-${step.id}`;
  const descId = `nbi-tour-desc-${step.id}`;
  // Arrow direction is the inverse of placement (a tooltip placed
  // ABOVE the anchor has its tail pointing DOWN). Center-placement
  // tooltips have no anchor, so no arrow.
  const arrowDirection = isCenter ? null : step.placement;
  return createPortal(
    <div
      ref={rootRef}
      className="nbi-tour-root"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descId}
    >
      {/* Scrim is non-dismissable on click: industry-standard tour UX.
          Skip / Done / Esc are the explicit exits, so a misclick on
          the dimmed area never abandons the tour. */}
      <div className="nbi-tour-scrim" />
      {spotlight}
      <div
        ref={tooltipRef}
        className={`nbi-tour-tooltip${isCenter ? ' nbi-tour-tooltip-center' : ''}`}
        style={tooltipStyle}
      >
        {arrowDirection && (
          <div
            className={`nbi-tour-arrow nbi-tour-arrow-${arrowDirection}`}
            aria-hidden="true"
          />
        )}
        <div
          className="nbi-tour-progress"
          role="progressbar"
          aria-valuemin={1}
          aria-valuemax={steps.length}
          aria-valuenow={index + 1}
          aria-label={`Tour progress: step ${index + 1} of ${steps.length}`}
        >
          <div
            className="nbi-tour-progress-bar"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div
          className="nbi-tour-body"
          aria-live="polite"
          aria-atomic="true"
          key={step.id}
        >
          <div className="nbi-tour-title" id={titleId}>
            {step.title}
          </div>
          <div className="nbi-tour-description" id={descId}>
            {step.description}
          </div>
        </div>
        <div className="nbi-tour-actions">
          <button type="button" className="nbi-tour-skip-link" onClick={finish}>
            {labels.skip}
          </button>
          <div style={{ flexGrow: 1 }} />
          {index > 0 && (
            <button
              type="button"
              className="jp-Dialog-button jp-mod-reject jp-mod-styled"
              onClick={back}
            >
              <div className="jp-Dialog-buttonLabel">{labels.back}</div>
            </button>
          )}
          <button
            type="button"
            className="jp-Dialog-button jp-mod-accept jp-mod-styled"
            onClick={advance}
            autoFocus
          >
            <div className="jp-Dialog-buttonLabel">
              {isLast ? labels.done : labels.next}
            </div>
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
