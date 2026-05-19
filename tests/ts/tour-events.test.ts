// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import {
  TOUR_START_EVENT,
  TOUR_STOP_EVENT,
  dispatchShowTour,
  dispatchHideTour
} from '../../src/tour/tour-events';

describe('tour-events', () => {
  it('round-trips show through the start event', () => {
    const listener = jest.fn();
    document.addEventListener(TOUR_START_EVENT, listener);
    dispatchShowTour();
    expect(listener).toHaveBeenCalledTimes(1);
    document.removeEventListener(TOUR_START_EVENT, listener);
  });

  it('round-trips hide through the stop event', () => {
    const listener = jest.fn();
    document.addEventListener(TOUR_STOP_EVENT, listener);
    dispatchHideTour();
    expect(listener).toHaveBeenCalledTimes(1);
    document.removeEventListener(TOUR_STOP_EVENT, listener);
  });

  it('uses distinct event names so listeners do not cross-fire', () => {
    const startListener = jest.fn();
    const stopListener = jest.fn();
    document.addEventListener(TOUR_START_EVENT, startListener);
    document.addEventListener(TOUR_STOP_EVENT, stopListener);
    dispatchShowTour();
    expect(startListener).toHaveBeenCalledTimes(1);
    expect(stopListener).not.toHaveBeenCalled();
    dispatchHideTour();
    expect(stopListener).toHaveBeenCalledTimes(1);
    document.removeEventListener(TOUR_START_EVENT, startListener);
    document.removeEventListener(TOUR_STOP_EVENT, stopListener);
  });
});
