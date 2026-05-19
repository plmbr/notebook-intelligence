// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import {
  TOUR_STORAGE_KEY,
  TOUR_VERSION,
  hasCompletedTour,
  markTourCompleted,
  resetTour
} from '../../src/tour/tour-state';

describe('tour-state', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('returns false when no entry exists', () => {
    expect(hasCompletedTour()).toBe(false);
  });

  it('round-trips through mark + has', () => {
    markTourCompleted();
    expect(hasCompletedTour()).toBe(true);
  });

  it('resetTour clears the flag', () => {
    markTourCompleted();
    resetTour();
    expect(hasCompletedTour()).toBe(false);
  });

  it('treats a stale version as not completed', () => {
    // Simulate a prior NBI release that wrote a different version
    // number; the current code should treat that as needing the tour
    // again so users see new onboarding content.
    window.localStorage.setItem(
      TOUR_STORAGE_KEY,
      JSON.stringify({ version: TOUR_VERSION - 1 })
    );
    expect(hasCompletedTour()).toBe(false);
  });

  it('treats a malformed entry as not completed', () => {
    window.localStorage.setItem(TOUR_STORAGE_KEY, 'not-json');
    // Must not throw; corrupt data is treated as "tour not done."
    expect(hasCompletedTour()).toBe(false);
  });

  it('writes the current version on mark', () => {
    markTourCompleted();
    const raw = window.localStorage.getItem(TOUR_STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string);
    expect(parsed.version).toBe(TOUR_VERSION);
  });
});
