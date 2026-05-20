// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import { FileDialog } from '@jupyterlab/filebrowser';
import { pickStartDirectory } from '../../src/coding-agent-launcher';

jest.mock('@jupyterlab/filebrowser', () => ({
  FileDialog: {
    getExistingDirectory: jest.fn()
  }
}));

const getExistingDirectory =
  FileDialog.getExistingDirectory as jest.MockedFunction<
    typeof FileDialog.getExistingDirectory
  >;

const fakeDocManager = {} as any;

describe('pickStartDirectory', () => {
  it('returns the path of the first selected directory when accepted', async () => {
    getExistingDirectory.mockResolvedValue({
      button: { accept: true } as any,
      value: [{ path: 'my-project' } as any]
    } as any);

    const result = await pickStartDirectory(
      fakeDocManager,
      'label',
      'workspace'
    );

    expect(result).toBe('my-project');
    expect(getExistingDirectory).toHaveBeenCalledWith({
      manager: fakeDocManager,
      title: 'label',
      label: 'label',
      defaultPath: 'workspace'
    });
  });

  it('preserves the empty string when the user picks the Jupyter root', async () => {
    // The root path is `''`. Treating it as falsy would silently
    // re-route the terminal to a different directory, so the caller
    // contract is: only `undefined` means "no selection".
    getExistingDirectory.mockResolvedValue({
      button: { accept: true } as any,
      value: [{ path: '' } as any]
    } as any);

    const result = await pickStartDirectory(fakeDocManager, 'label');

    expect(result).toBe('');
  });

  it('returns undefined when the user cancels the dialog', async () => {
    getExistingDirectory.mockResolvedValue({
      button: { accept: false } as any,
      value: null
    } as any);

    const result = await pickStartDirectory(fakeDocManager, 'label');

    expect(result).toBeUndefined();
  });

  it('falls back to defaultPath when accepted with an empty value array', async () => {
    // JupyterLab populates value with the browser's current path when
    // nothing is selected, so this branch is defensive. If it ever
    // triggers, fall back to the caller-supplied default rather than
    // silently launching at the Jupyter root.
    getExistingDirectory.mockResolvedValue({
      button: { accept: true } as any,
      value: []
    } as any);

    const result = await pickStartDirectory(
      fakeDocManager,
      'label',
      'workspace'
    );

    expect(result).toBe('workspace');
  });

  it('returns an empty string when accepted with no value and no default', async () => {
    getExistingDirectory.mockResolvedValue({
      button: { accept: true } as any,
      value: null
    } as any);

    const result = await pickStartDirectory(fakeDocManager, 'label');

    expect(result).toBe('');
  });
});
