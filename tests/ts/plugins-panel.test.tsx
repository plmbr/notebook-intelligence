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
    expect(selects).toHaveLength(3);
    expect(selects[0].value).toBe('official');
    expect(selects[1].value).toBe('alpha');

    fireEvent.change(selects[1], { target: { value: 'beta' } });
    fireEvent.click(screen.getByRole('button', { name: 'Install' }));

    await waitFor(() => {
      expect(api.installPlugin).toHaveBeenCalledWith('beta@official', 'user');
    });
  });
});
