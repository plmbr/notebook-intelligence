// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

/**
 * Admin tour-copy overrides — frontend half.
 *
 * The backend reads a YAML/JSON file (path from `NBI_TOUR_CONFIG_PATH`)
 * and ships the validated overrides via the capabilities response. This
 * module overlays them on the built-in `ALL_TOUR_STEPS` so the same
 * tour code runs against either the default copy or an admin-supplied
 * customization, without rebuilding the extension.
 *
 * Defense in depth: the backend already validated shape and length;
 * the frontend re-applies the same caps here so a backend bug or
 * future server-side regression can't crash the picker layout.
 */

import { ITourStep } from './tour-steps';

// Per-field length caps. Mirror notebook_intelligence/tour_config.py.
const MAX_TITLE_CHARS = 80;
const MAX_DESCRIPTION_CHARS = 400;
const MAX_BUTTON_LABEL_CHARS = 24;
const MAX_COMMAND_LABEL_CHARS = 40;

export interface ITourStepOverride {
  title?: string;
  description?: string;
  enabled?: boolean;
  // Launcher-tiles step only: templates rendered with `{launchers}`
  // substituted by the comma-joined list of installed CLI tools.
  description_singular?: string;
  description_plural?: string;
}

export interface ITourUiOverride {
  skip?: string;
  next?: string;
  back?: string;
  done?: string;
}

export interface ITourCommandOverride {
  label?: string;
}

export interface ITourOverrides {
  steps?: Record<string, ITourStepOverride>;
  ui?: ITourUiOverride;
  command?: ITourCommandOverride;
}

function clamp(value: string, limit: number): string {
  return value.length <= limit ? value : value.slice(0, limit);
}

/**
 * Apply admin-supplied overrides to the canonical step list. Returns a
 * new array; the input is not mutated.
 *
 * Override semantics:
 *  - `enabled: false` drops the step entirely (filtered out here, in
 *    addition to whatever `requires()` says).
 *  - `title` / `description` replace the corresponding fields when set.
 *  - For `launcher-tiles`, the dynamic thunk continues to run; the
 *    templates feed into it through the per-step override dict so the
 *    thunk can use them at resolve time.
 */
export function applyTourOverrides(
  steps: readonly ITourStep[],
  overrides: ITourOverrides | undefined
): ITourStep[] {
  if (!overrides || !overrides.steps) {
    return steps.map(step => ({ ...step }));
  }
  const stepOverrides = overrides.steps;
  const result: ITourStep[] = [];
  for (const step of steps) {
    const override = stepOverrides[step.id];
    if (!override) {
      result.push({ ...step });
      continue;
    }
    if (override.enabled === false) {
      continue;
    }
    const next: ITourStep = { ...step };
    // Reject empty strings: an empty title would leave the dialog's
    // aria-labelledby target with no accessible name, and an empty
    // description would leave aria-describedby pointing at nothing.
    if (typeof override.title === 'string' && override.title.length > 0) {
      next.title = clamp(override.title, MAX_TITLE_CHARS);
    }
    if (
      typeof override.description === 'string' &&
      override.description.length > 0 &&
      // The launcher-tiles thunk is overridden via templates, not the
      // plain `description` field; the backend validator rejects it
      // outright, but ignore it here too in case an older payload slips
      // through.
      step.id !== 'launcher-tiles'
    ) {
      next.description = clamp(override.description, MAX_DESCRIPTION_CHARS);
    }
    result.push(next);
  }
  return result;
}

/**
 * Pull the per-step override for the launcher-tiles step's templates
 * (if any). Used by the launcher-tiles description thunk.
 */
export function launcherTileTemplates(overrides: ITourOverrides | undefined): {
  singular?: string;
  plural?: string;
} {
  const step = overrides?.steps?.['launcher-tiles'];
  if (!step) {
    return {};
  }
  const result: { singular?: string; plural?: string } = {};
  if (typeof step.description_singular === 'string') {
    result.singular = clamp(step.description_singular, MAX_DESCRIPTION_CHARS);
  }
  if (typeof step.description_plural === 'string') {
    result.plural = clamp(step.description_plural, MAX_DESCRIPTION_CHARS);
  }
  return result;
}

/**
 * Resolve a UI button label: admin override if set, otherwise the
 * default supplied by the caller.
 */
export function uiLabel(
  overrides: ITourOverrides | undefined,
  key: keyof ITourUiOverride,
  fallback: string
): string {
  const raw = overrides?.ui?.[key];
  if (typeof raw === 'string' && raw.length > 0) {
    return clamp(raw, MAX_BUTTON_LABEL_CHARS);
  }
  return fallback;
}

/**
 * Resolve the command-palette label for the tour command: admin
 * override if set, otherwise the default supplied by the caller.
 */
export function commandLabel(
  overrides: ITourOverrides | undefined,
  fallback: string
): string {
  const raw = overrides?.command?.label;
  if (typeof raw === 'string' && raw.length > 0) {
    return clamp(raw, MAX_COMMAND_LABEL_CHARS);
  }
  return fallback;
}
