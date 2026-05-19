// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

/**
 * localStorage-backed persistence for the first-run tour.
 *
 * The tour is shown exactly once per browser per major tour version. The
 * version is bumped (in code) whenever the step set changes meaningfully
 * so existing users get re-prompted instead of silently missing new
 * onboarding content. Users can also re-run the tour on demand via the
 * `notebook-intelligence:show-tour` command, which calls `resetTour()`.
 *
 * Why localStorage and not server-side state: the tour is purely UI; a
 * round trip to the Jupyter server on every sidebar mount just to check
 * a single flag would add latency to a hot path. localStorage is
 * per-browser, which is the right granularity (a user signing in on a
 * second browser benefits from seeing the tour again).
 */

// Bump when the tour's step set changes meaningfully enough to want
// existing users to re-see it. Keys older than the current version are
// ignored, and writes always use the current version.
export const TOUR_VERSION = 1;
// Exported so tests can clear the same key the production code writes,
// instead of duplicating the string literal.
export const TOUR_STORAGE_KEY = 'nbi.tour.completed';
const TOUR_KEY = TOUR_STORAGE_KEY;

interface ITourRecord {
  version: number;
}

function safeStorage(): Storage | null {
  // localStorage can throw under some sandboxed iframe / privacy modes;
  // a thrown access here would crash the sidebar mount. Treat absence
  // as "tour was never completed" rather than failing closed.
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function hasCompletedTour(): boolean {
  const storage = safeStorage();
  if (!storage) {
    return false;
  }
  const raw = storage.getItem(TOUR_KEY);
  if (!raw) {
    return false;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<ITourRecord>;
    return parsed?.version === TOUR_VERSION;
  } catch {
    // Stale / corrupt entry from an older NBI version. Treat as not
    // completed; the next markCompleted will overwrite with the current
    // shape.
    return false;
  }
}

export function markTourCompleted(): void {
  const storage = safeStorage();
  if (!storage) {
    return;
  }
  try {
    storage.setItem(TOUR_KEY, JSON.stringify({ version: TOUR_VERSION }));
  } catch {
    // Quota exceeded / private mode rejecting writes. Worst case the
    // tour fires again on the next sidebar mount, which is preferable
    // to crashing the sidebar.
  }
}

export function resetTour(): void {
  const storage = safeStorage();
  if (!storage) {
    return;
  }
  try {
    storage.removeItem(TOUR_KEY);
  } catch {
    // See markTourCompleted.
  }
}
