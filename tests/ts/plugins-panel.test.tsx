// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('../../src/api', () => ({
  NBIAPI: {
    config: {
      allowGithubPluginImport: true
    },
    configChanged: {
      connect: jest.fn(),
      disconnect: jest.fn()
    },
    listPlugins: jest.fn(),
    listPluginMarketplaces: jest.fn(),
    listPluginMarketplacePlugins: jest.fn(),
    installPlugin: jest.fn()
  }
}));

import { NBIAPI } from '../../src/api';
import { SettingsPanelComponentPlugins } from '../../src/components/plugins-panel';

describe('SettingsPanelComponentPlugins', () => {
  const api = NBIAPI as any;

  beforeEach(() => {
    jest.clearAllMocks();
    document.body.innerHTML = '';
    api.listPlugins.mockResolvedValue([]);
    api.listPluginMarketplaces.mockResolvedValue([
      { name: 'official', source: 'github:anthropics/claude-code' }
    ]);
    api.listPluginMarketplacePlugins.mockResolvedValue([
      { name: 'alpha', description: 'Alpha plugin' },
      { name: 'beta', description: 'Beta plugin' }
    ]);
    api.installPlugin.mockResolvedValue(undefined);
  });

  it('installs the selected plugin from the selected marketplace', async () => {
    render(<SettingsPanelComponentPlugins />);

    await screen.findByText('official');
    fireEvent.click(screen.getByRole('button', { name: 'Install plugin' }));

    await waitFor(() => {
      expect(api.listPluginMarketplacePlugins).toHaveBeenCalledWith('official');
    });

    const selects = Array.from(
      document.querySelectorAll('.nbi-modal-card select')
    ) as HTMLSelectElement[];
    expect(selects).toHaveLength(4);
    expect(selects[0].value).toBe('marketplace');
    expect(selects[1].value).toBe('official');
    expect(selects[2].value).toBe('alpha');

    fireEvent.change(selects[2], { target: { value: 'beta' } });
    fireEvent.click(screen.getByRole('button', { name: 'Install' }));

    await waitFor(() => {
      expect(api.installPlugin).toHaveBeenCalledWith('beta@official', 'user');
    });
  });

  it('allows a plugin reference to be specified manually', async () => {
    render(<SettingsPanelComponentPlugins />);

    await screen.findByText('official');
    fireEvent.click(screen.getByRole('button', { name: 'Install plugin' }));

    const selects = Array.from(
      document.querySelectorAll('.nbi-modal-card select')
    ) as HTMLSelectElement[];
    fireEvent.change(selects[0], { target: { value: 'manual' } });

    const input = document.querySelector(
      '.nbi-modal-card input[type="text"]'
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '  gamma@official  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Install' }));

    await waitFor(() => {
      expect(api.installPlugin).toHaveBeenCalledWith('gamma@official', 'user');
    });
  });

  it('keeps manual install available when no marketplace cache is configured', async () => {
    api.listPluginMarketplaces.mockResolvedValue([]);

    render(<SettingsPanelComponentPlugins />);

    await screen.findByText(
      'No marketplaces configured. Add one to discover plugins.'
    );
    fireEvent.click(screen.getByRole('button', { name: 'Install plugin' }));

    const input = document.querySelector(
      '.nbi-modal-card input[type="text"]'
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'manual-plugin@official' } });
    fireEvent.click(screen.getByRole('button', { name: 'Install' }));

    await waitFor(() => {
      expect(api.installPlugin).toHaveBeenCalledWith(
        'manual-plugin@official',
        'user'
      );
    });
    expect(api.listPluginMarketplacePlugins).not.toHaveBeenCalled();
  });

  it('uses marketplace plugin id when name is absent', async () => {
    api.listPluginMarketplacePlugins.mockResolvedValue([
      { id: 'id-only', description: 'ID-only plugin' }
    ]);

    render(<SettingsPanelComponentPlugins />);

    await screen.findByText('official');
    fireEvent.click(screen.getByRole('button', { name: 'Install plugin' }));

    await waitFor(() => {
      expect(api.listPluginMarketplacePlugins).toHaveBeenCalledWith('official');
    });

    const selects = Array.from(
      document.querySelectorAll('.nbi-modal-card select')
    ) as HTMLSelectElement[];
    expect(selects[2].value).toBe('id-only');
    fireEvent.click(screen.getByRole('button', { name: 'Install' }));

    await waitFor(() => {
      expect(api.installPlugin).toHaveBeenCalledWith(
        'id-only@official',
        'user'
      );
    });
  });
});
