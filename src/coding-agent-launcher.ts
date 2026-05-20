// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import { IDocumentManager } from '@jupyterlab/docmanager';
import { FileDialog } from '@jupyterlab/filebrowser';

// Prompt the user for a start directory for a coding-agent terminal.
// Returns the chosen path relative to the Jupyter server root (`''`
// means the root itself — a valid selection, not a sentinel), or
// `undefined` if the user cancelled the dialog.
export async function pickStartDirectory(
  docManager: IDocumentManager,
  label: string,
  defaultPath?: string
): Promise<string | undefined> {
  const result = await FileDialog.getExistingDirectory({
    manager: docManager,
    title: label,
    label,
    defaultPath
  });
  if (!result.button.accept) {
    return undefined;
  }
  // JupyterLab's FileDialog falls back to the file browser's current
  // path when nothing is selected, so result.value is normally a
  // single-element array. The empty-array branch is purely defensive.
  const value = result.value;
  return value && value.length > 0 ? value[0].path : (defaultPath ?? '');
}
