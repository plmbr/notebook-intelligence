import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import {
  BYPASS_PERMISSIONS_MODE,
  PermissionModeSelect
} from '../../src/components/permission-mode-select';

function openMenu() {
  fireEvent.click(screen.getByRole('button', { name: /Permission mode/ }));
}

describe('PermissionModeSelect', () => {
  it('shows the current mode on the trigger button', () => {
    render(
      <PermissionModeSelect
        value="plan"
        bypassAllowed={false}
        onModeChange={jest.fn()}
      />
    );
    expect(
      screen.getByRole('button', { name: 'Permission mode: Plan' })
    ).toBeInTheDocument();
  });

  it('lists the three normal modes and hides bypass when not allowed', () => {
    render(
      <PermissionModeSelect
        value="default"
        bypassAllowed={false}
        onModeChange={jest.fn()}
      />
    );
    openMenu();
    const items = screen.getAllByRole('menuitemradio').map(i => i.textContent);
    expect(items).toEqual(['Default', 'Accept Edits', 'Plan']);
  });

  it('lists bypass when the policy allows it', () => {
    render(
      <PermissionModeSelect
        value="default"
        bypassAllowed={true}
        onModeChange={jest.fn()}
      />
    );
    openMenu();
    expect(
      screen.getByRole('menuitemradio', { name: 'Bypass Permissions' })
    ).toBeInTheDocument();
  });

  it('marks the active mode as checked', () => {
    render(
      <PermissionModeSelect
        value="acceptEdits"
        bypassAllowed={false}
        onModeChange={jest.fn()}
      />
    );
    openMenu();
    expect(
      screen.getByRole('menuitemradio', { name: 'Accept Edits' })
    ).toHaveAttribute('aria-checked', 'true');
    expect(
      screen.getByRole('menuitemradio', { name: 'Default' })
    ).toHaveAttribute('aria-checked', 'false');
  });

  it('switches normal modes immediately and closes the menu', () => {
    const onModeChange = jest.fn();
    render(
      <PermissionModeSelect
        value="default"
        bypassAllowed={true}
        onModeChange={onModeChange}
      />
    );
    openMenu();
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'Plan' }));
    expect(onModeChange).toHaveBeenCalledWith('plan');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('requires the confirm-to-arm step before bypass takes effect', () => {
    const onModeChange = jest.fn();
    render(
      <PermissionModeSelect
        value="default"
        bypassAllowed={true}
        onModeChange={onModeChange}
      />
    );
    openMenu();
    fireEvent.click(
      screen.getByRole('menuitemradio', { name: 'Bypass Permissions' })
    );
    // Choosing bypass closes the menu and opens the confirm dialog without
    // switching the mode.
    expect(onModeChange).not.toHaveBeenCalled();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Bypass permissions'));
    expect(onModeChange).toHaveBeenCalledWith(BYPASS_PERMISSIONS_MODE);
  });

  it('cancelling the arm step leaves the mode unchanged', () => {
    const onModeChange = jest.fn();
    render(
      <PermissionModeSelect
        value="plan"
        bypassAllowed={true}
        onModeChange={onModeChange}
      />
    );
    openMenu();
    fireEvent.click(
      screen.getByRole('menuitemradio', { name: 'Bypass Permissions' })
    );
    fireEvent.click(screen.getByText('Cancel'));
    expect(onModeChange).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('Escape dismisses the confirm dialog without arming', () => {
    const onModeChange = jest.fn();
    render(
      <PermissionModeSelect
        value="default"
        bypassAllowed={true}
        onModeChange={onModeChange}
      />
    );
    openMenu();
    fireEvent.click(
      screen.getByRole('menuitemradio', { name: 'Bypass Permissions' })
    );
    fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Escape' });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(onModeChange).not.toHaveBeenCalled();
  });

  it('ArrowDown/ArrowUp move focus between menu items', () => {
    render(
      <PermissionModeSelect
        value="default"
        bypassAllowed={false}
        onModeChange={jest.fn()}
      />
    );
    openMenu();
    // Opens with focus on the checked item (Default, index 0).
    expect(
      screen.getByRole('menuitemradio', { name: 'Default' })
    ).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowDown' });
    expect(
      screen.getByRole('menuitemradio', { name: 'Accept Edits' })
    ).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowUp' });
    expect(
      screen.getByRole('menuitemradio', { name: 'Default' })
    ).toHaveFocus();
    // Wraps from the first item up to the last.
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowUp' });
    expect(screen.getByRole('menuitemradio', { name: 'Plan' })).toHaveFocus();
  });

  it('Escape closes the menu', () => {
    render(
      <PermissionModeSelect
        value="default"
        bypassAllowed={true}
        onModeChange={jest.fn()}
      />
    );
    openMenu();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('moves focus into the confirm dialog when it opens', () => {
    render(
      <PermissionModeSelect
        value="default"
        bypassAllowed={true}
        onModeChange={jest.fn()}
      />
    );
    openMenu();
    fireEvent.click(
      screen.getByRole('menuitemradio', { name: 'Bypass Permissions' })
    );
    expect(screen.getByText('Cancel')).toHaveFocus();
  });

  it('shows the armed indicator and aria-label while bypass is active', () => {
    render(
      <PermissionModeSelect
        value={BYPASS_PERMISSIONS_MODE}
        bypassAllowed={true}
        onModeChange={jest.fn()}
      />
    );
    const button = screen.getByRole('button', {
      name: 'Permission mode: Bypass Permissions is active'
    });
    expect(button).toHaveClass('permission-mode-button-bypass');
  });

  it('keeps bypass listed if the policy flips while it is active', () => {
    // The sidebar resets the mode when the policy flips; until that lands,
    // the active bypass must remain visible/selectable in the menu.
    render(
      <PermissionModeSelect
        value={BYPASS_PERMISSIONS_MODE}
        bypassAllowed={false}
        onModeChange={jest.fn()}
      />
    );
    openMenu();
    expect(
      screen.getByRole('menuitemradio', { name: 'Bypass Permissions' })
    ).toHaveAttribute('aria-checked', 'true');
  });
});
