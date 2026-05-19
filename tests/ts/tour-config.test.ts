// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import { ITourStep } from '../../src/tour/tour-steps';
import {
  applyTourOverrides,
  commandLabel,
  launcherTileTemplates,
  uiLabel
} from '../../src/tour/tour-config';

function makeStep(id: string, title: string, description: string): ITourStep {
  return {
    id,
    title,
    description,
    anchorId: null,
    placement: 'center'
  };
}

const DEFAULT_STEPS: ITourStep[] = [
  makeStep('welcome', 'Welcome', 'Default welcome.'),
  makeStep('drag-and-drop', 'Drag and drop', 'Default drag-and-drop.'),
  {
    id: 'launcher-tiles',
    title: 'Run an agent',
    description: () => 'thunk default',
    anchorId: null,
    placement: 'center'
  },
  makeStep('done', "You're ready", 'Default done.')
];

describe('applyTourOverrides', () => {
  it('returns the input unchanged when overrides are undefined', () => {
    const out = applyTourOverrides(DEFAULT_STEPS, undefined);
    expect(out).toHaveLength(DEFAULT_STEPS.length);
    expect(out[0].title).toBe('Welcome');
    expect(out[0].description).toBe('Default welcome.');
    // New array, not the same reference.
    expect(out).not.toBe(DEFAULT_STEPS);
  });

  it('returns the input unchanged when overrides have no `steps`', () => {
    const out = applyTourOverrides(DEFAULT_STEPS, { ui: { skip: 'X' } });
    expect(out[0].title).toBe('Welcome');
    expect(out[1].title).toBe('Drag and drop');
  });

  it('overrides title and description per step', () => {
    const out = applyTourOverrides(DEFAULT_STEPS, {
      steps: {
        welcome: { title: 'Hi team', description: 'Override copy.' }
      }
    });
    expect(out[0].title).toBe('Hi team');
    expect(out[0].description).toBe('Override copy.');
    // Other steps untouched.
    expect(out[1].title).toBe('Drag and drop');
  });

  it('drops a step when enabled is false', () => {
    const out = applyTourOverrides(DEFAULT_STEPS, {
      steps: { 'drag-and-drop': { enabled: false } }
    });
    const ids = out.map(s => s.id);
    expect(ids).toEqual(['welcome', 'launcher-tiles', 'done']);
  });

  it('does not replace the launcher-tiles thunk via plain description', () => {
    // The launcher-tiles step's description is a function (thunk); admins
    // override it via description_singular / _plural instead. A stray
    // `description:` field on that step should be ignored so the dynamic
    // CLI listing keeps working.
    const out = applyTourOverrides(DEFAULT_STEPS, {
      steps: {
        'launcher-tiles': { description: 'static override' }
      }
    });
    const launcher = out.find(s => s.id === 'launcher-tiles');
    expect(typeof launcher!.description).toBe('function');
  });

  it('clamps long titles and descriptions to the configured caps', () => {
    const longTitle = 'x'.repeat(200);
    const longDesc = 'y'.repeat(800);
    const out = applyTourOverrides(DEFAULT_STEPS, {
      steps: {
        welcome: { title: longTitle, description: longDesc }
      }
    });
    expect(out[0].title.length).toBe(80);
    expect((out[0].description as string).length).toBe(400);
  });

  it('ignores overrides for unknown step ids (no insertion)', () => {
    const out = applyTourOverrides(DEFAULT_STEPS, {
      steps: { 'nonexistent-step': { title: 'oops' } }
    });
    expect(out.map(s => s.id)).toEqual([
      'welcome',
      'drag-and-drop',
      'launcher-tiles',
      'done'
    ]);
  });
});

describe('launcherTileTemplates', () => {
  it('returns empty when no launcher-tiles override is present', () => {
    expect(launcherTileTemplates(undefined)).toEqual({});
    expect(launcherTileTemplates({})).toEqual({});
    expect(launcherTileTemplates({ steps: {} })).toEqual({});
  });

  it('returns singular and plural templates when set', () => {
    const t = launcherTileTemplates({
      steps: {
        'launcher-tiles': {
          description_singular: '{launchers} opens a terminal.',
          description_plural: 'Each of {launchers} opens a terminal.'
        }
      }
    });
    expect(t.singular).toBe('{launchers} opens a terminal.');
    expect(t.plural).toBe('Each of {launchers} opens a terminal.');
  });

  it('clamps long templates', () => {
    const t = launcherTileTemplates({
      steps: {
        'launcher-tiles': { description_singular: 'a'.repeat(800) }
      }
    });
    expect(t.singular!.length).toBe(400);
  });
});

describe('uiLabel', () => {
  it('returns the fallback when no override is set', () => {
    expect(uiLabel(undefined, 'skip', 'Skip')).toBe('Skip');
    expect(uiLabel({}, 'next', 'Next')).toBe('Next');
    expect(uiLabel({ ui: {} }, 'back', 'Back')).toBe('Back');
  });

  it('returns the override when set', () => {
    expect(uiLabel({ ui: { skip: 'Dismiss' } }, 'skip', 'Skip')).toBe(
      'Dismiss'
    );
  });

  it('falls back when the override is an empty string', () => {
    expect(uiLabel({ ui: { next: '' } }, 'next', 'Next')).toBe('Next');
  });

  it('clamps an overlong label', () => {
    const label = uiLabel({ ui: { done: 'x'.repeat(80) } }, 'done', 'Done');
    expect(label.length).toBe(24);
  });
});

describe('commandLabel', () => {
  it('returns the fallback when no override is set', () => {
    expect(commandLabel(undefined, 'Show NBI tour')).toBe('Show NBI tour');
    expect(commandLabel({}, 'Show NBI tour')).toBe('Show NBI tour');
    expect(commandLabel({ command: {} }, 'Show NBI tour')).toBe(
      'Show NBI tour'
    );
  });

  it('returns the override when set', () => {
    expect(
      commandLabel(
        { command: { label: 'Replay ACME walkthrough' } },
        'Show NBI tour'
      )
    ).toBe('Replay ACME walkthrough');
  });

  it('falls back when the override is an empty string', () => {
    expect(commandLabel({ command: { label: '' } }, 'Show NBI tour')).toBe(
      'Show NBI tour'
    );
  });

  it('clamps an overlong label', () => {
    const label = commandLabel(
      { command: { label: 'x'.repeat(80) } },
      'Show NBI tour'
    );
    expect(label.length).toBe(40);
  });
});
