// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

// Stub for @jupyterlab/filebrowser. The real package is ESM and pulls in
// transitive ESM deps that jest's CommonJS pipeline can't load. Tests
// that need behavior here re-mock FileDialog locally.

export const FileDialog = {
  getExistingDirectory: jest.fn()
};
