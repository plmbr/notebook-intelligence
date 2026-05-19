// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

// Capabilities flags consumed by tour-steps. Default everything off; per
// test we override what's needed.
jest.mock('../../src/api', () => ({
  NBIAPI: {
    config: {
      isClaudeCliAvailable: false,
      isCodexCliAvailable: false,
      isOpenCodeCliAvailable: false,
      isPiCliAvailable: false,
      isGitHubCopilotCliAvailable: false,
      isInClaudeCodeMode: false,
      isCodingAgentLauncherDisabledByPolicy: (_id: string) => false,
      tourOverrides: {}
    }
  }
}));

import { NBIAPI } from '../../src/api';
import { TourOverlay } from '../../src/tour/tour-overlay';
import { hasCompletedTour, resetTour } from '../../src/tour/tour-state';
import { ALL_TOUR_STEPS, TOUR_DEFAULTS } from '../../src/tour/tour-steps';

const api = NBIAPI as any;

function mountAnchor(id: string): HTMLElement {
  const el = document.createElement('button');
  el.setAttribute('data-tour-id', id);
  el.textContent = id;
  document.body.appendChild(el);
  return el;
}

describe('TourOverlay', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    window.localStorage.clear();
    api.config.isClaudeCliAvailable = false;
    api.config.isCodexCliAvailable = false;
    api.config.isOpenCodeCliAvailable = false;
    api.config.isPiCliAvailable = false;
    api.config.isGitHubCopilotCliAvailable = false;
    api.config.isInClaudeCodeMode = false;
    api.config.tourOverrides = {};
  });

  it('walks the welcome -> done flow and marks completed', async () => {
    mountAnchor('settings-gear');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    mountAnchor('chat-mode');
    // Light up one coding-agent CLI so the launcher-tiles step
    // remains in the walk (otherwise it's gated out by the capability
    // requires() predicate).
    api.config.isClaudeCliAvailable = true;

    const onClose = jest.fn();
    render(<TourOverlay onClose={onClose} />);

    await screen.findByText('Welcome to Notebook Intelligence');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Settings');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Run a slash command');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Attach files as context');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Upload from your computer');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Drag and drop');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Pick a chat mode');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Run a coding agent in a terminal');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText("You're ready");
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(hasCompletedTour()).toBe(true);
  });

  it('Skip dismisses immediately and marks completed', async () => {
    mountAnchor('settings-gear');
    const onClose = jest.fn();
    render(<TourOverlay onClose={onClose} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    fireEvent.click(screen.getByRole('button', { name: 'Skip tour' }));
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(hasCompletedTour()).toBe(true);
  });

  it('skips Claude + launcher steps when no agent CLI is installed', async () => {
    mountAnchor('settings-gear');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    mountAnchor('chat-mode');
    // Even when anchors for the Claude-only steps are present, their
    // capability predicates filter them out. The launcher-tiles step
    // also drops because no coding-agent CLI is available. Remaining:
    // welcome, settings, slash, add-context, upload, drag-and-drop,
    // chat-mode, done — 8 steps.
    mountAnchor('new-chat');
    mountAnchor('claude-history');

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '1');
    expect(bar).toHaveAttribute('aria-valuemax', '8');
  });

  it('includes the Claude-only steps when CLI + mode both engaged', async () => {
    api.config.isClaudeCliAvailable = true;
    api.config.isInClaudeCodeMode = true;
    mountAnchor('new-chat');
    mountAnchor('settings-gear');
    mountAnchor('claude-history');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    // Chat-mode step is hidden when Claude mode is on. With both
    // Claude-only steps added and chat-mode dropped, the count lands
    // at 9.

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '1');
    expect(bar).toHaveAttribute('aria-valuemax', '10');
  });

  it('auto-skips a step whose anchor is missing from the DOM', async () => {
    // settings-gear anchor is deliberately not mounted. The tour should
    // jump past that step to the next one with a present anchor.
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('chat-mode');

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    // Should auto-advance past the missing gear anchor straight to
    // the next step with a present anchor.
    await screen.findByText('Run a slash command');
  });

  it('Esc key dismisses the tour', async () => {
    mountAnchor('settings-gear');
    const onClose = jest.fn();
    render(<TourOverlay onClose={onClose} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(hasCompletedTour()).toBe(true);
  });

  it('Back returns to the previous step', async () => {
    mountAnchor('settings-gear');
    mountAnchor('add-context');
    mountAnchor('chat-mode');
    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    // Welcome has no Back button.
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Settings');
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    await screen.findByText('Welcome to Notebook Intelligence');
  });

  it('launcher-tiles step names only installed coding-agent CLIs', async () => {
    // With just Claude available, the description should mention it as
    // a single tile (not "tiles ... for Claude Code and Codex" the way
    // the old hardcoded copy claimed even when Codex was absent).
    api.config.isClaudeCliAvailable = true;
    mountAnchor('settings-gear');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    mountAnchor('chat-mode');

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    for (let i = 0; i < 7; i++) {
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    }
    await screen.findByText('Run a coding agent in a terminal');
    // Singular language + name of the one installed CLI.
    expect(
      screen.getByText(/has a Claude Code tile in the 'Coding Agent' section/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/Claude Code and Codex/)).not.toBeInTheDocument();
  });

  it('launcher-tiles step lists multiple installed CLIs with commas', async () => {
    api.config.isClaudeCliAvailable = true;
    api.config.isCodexCliAvailable = true;
    api.config.isOpenCodeCliAvailable = true;
    mountAnchor('settings-gear');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    mountAnchor('chat-mode');

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    for (let i = 0; i < 7; i++) {
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    }
    expect(
      screen.getByText(/Claude Code, Codex, and opencode/)
    ).toBeInTheDocument();
  });

  it('skips the launcher-tiles step entirely when no CLI is installed', async () => {
    // No coding-agent CLI flags set — the launcher-tiles step should be
    // gated out so the tour doesn't promise an affordance the user
    // cannot reach.
    mountAnchor('settings-gear');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    mountAnchor('chat-mode');

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    for (let i = 0; i < 7; i++) {
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    }
    // Last anchored step ('Pick a chat mode') -> next click should jump
    // straight to the done step, skipping launcher-tiles.
    expect(
      screen.queryByText('Run a coding agent in a terminal')
    ).not.toBeInTheDocument();
    await screen.findByText("You're ready");
  });

  it('respects admin policy that hides specific coding-agent tiles', async () => {
    api.config.isClaudeCliAvailable = true;
    api.config.isCodexCliAvailable = true;
    // Admin policy drops Codex from the Launcher even though the CLI
    // is on PATH; the tour must follow suit.
    api.config.isCodingAgentLauncherDisabledByPolicy = (id: string) =>
      id === 'codex';
    mountAnchor('settings-gear');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    mountAnchor('chat-mode');

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    for (let i = 0; i < 7; i++) {
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    }
    await screen.findByText('Run a coding agent in a terminal');
    // Singular phrasing because the policy hid Codex.
    expect(screen.getByText(/has a Claude Code tile/)).toBeInTheDocument();
    expect(screen.queryByText(/Codex/)).not.toBeInTheDocument();
  });

  it('honors an admin override that rewrites the welcome copy', async () => {
    api.config.tourOverrides = {
      steps: {
        welcome: {
          title: 'Welcome to ACME AI',
          description: 'Custom welcome. Press Esc to skip.'
        }
      }
    };
    mountAnchor('settings-gear');
    render(<TourOverlay onClose={jest.fn()} />);

    await screen.findByText('Welcome to ACME AI');
    expect(
      screen.getByText('Custom welcome. Press Esc to skip.')
    ).toBeInTheDocument();
    // Default title is no longer rendered.
    expect(
      screen.queryByText('Welcome to Notebook Intelligence')
    ).not.toBeInTheDocument();
  });

  it('drops a step when the admin override sets enabled=false', async () => {
    api.config.tourOverrides = {
      steps: { 'drag-and-drop': { enabled: false } }
    };
    mountAnchor('settings-gear');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    mountAnchor('chat-mode');

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    const bar = screen.getByRole('progressbar');
    // 8 default - 1 (drag-and-drop dropped) = 7; launcher-tiles still
    // gated by capability (no CLI available), so final is 7.
    expect(bar).toHaveAttribute('aria-valuemax', '7');
  });

  it('substitutes admin launcher-tiles templates with the CLI list', async () => {
    api.config.isClaudeCliAvailable = true;
    api.config.tourOverrides = {
      steps: {
        'launcher-tiles': {
          description_singular: 'Run {launchers} from the Launcher.',
          description_plural: 'Each of {launchers} runs from the Launcher.'
        }
      }
    };
    mountAnchor('settings-gear');
    mountAnchor('slash-commands');
    mountAnchor('add-context');
    mountAnchor('upload-file');
    mountAnchor('prompt-input');
    mountAnchor('chat-mode');

    render(<TourOverlay onClose={jest.fn()} />);
    await screen.findByText('Welcome to Notebook Intelligence');
    for (let i = 0; i < 7; i++) {
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    }
    expect(
      screen.getByText('Run Claude Code from the Launcher.')
    ).toBeInTheDocument();
  });

  it('renders admin-overridden button labels', async () => {
    api.config.tourOverrides = {
      ui: {
        skip: 'Dismiss',
        next: 'Forward',
        back: 'Reverse',
        done: 'Finish'
      }
    };
    mountAnchor('settings-gear');
    render(<TourOverlay onClose={jest.fn()} />);

    // Welcome step: Skip and Next labels visible; no Back yet.
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Forward' })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Skip tour' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Next' })
    ).not.toBeInTheDocument();

    // Advance one step so the Back button appears.
    fireEvent.click(screen.getByRole('button', { name: 'Forward' }));
    await screen.findByRole('button', { name: 'Reverse' });
  });

  it('exposes the override title as the dialog accessible name', async () => {
    api.config.tourOverrides = {
      steps: {
        welcome: { title: 'Welcome to ACME AI', description: 'Hi.' }
      }
    };
    mountAnchor('settings-gear');
    render(<TourOverlay onClose={jest.fn()} />);

    // aria-labelledby resolves to the overridden title.
    expect(
      await screen.findByRole('dialog', { name: 'Welcome to ACME AI' })
    ).toBeInTheDocument();
  });

  it('ignores an empty-string override title so the default copy stays', async () => {
    // Defense in depth: backend rejects empty strings, but the
    // frontend should not blank out the dialog if a payload from an
    // older backend ever slips through.
    api.config.tourOverrides = {
      steps: { welcome: { title: '', description: '' } }
    };
    mountAnchor('settings-gear');
    render(<TourOverlay onClose={jest.fn()} />);

    await screen.findByText('Welcome to Notebook Intelligence');
    expect(
      screen.getByRole('dialog', { name: 'Welcome to Notebook Intelligence' })
    ).toBeInTheDocument();
  });

  afterEach(() => {
    resetTour();
  });

  // Schema-drift pin: the bundled defaults file is the single source
  // for tour copy, but step ids must stay in lockstep with the live
  // step list and (separately, in test_tour_config.py) with the Python
  // validator's allowlist. A copy-only edit to the JSON cannot silently
  // desync any of the three.
  it('TOUR_DEFAULTS step ids match ALL_TOUR_STEPS', () => {
    const liveIds = new Set(ALL_TOUR_STEPS.map(s => s.id));
    const jsonIds = new Set(Object.keys(TOUR_DEFAULTS.steps ?? {}));
    expect(jsonIds).toEqual(liveIds);
  });
});
