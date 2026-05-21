// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/tests/ts/setup.ts'],
  testMatch: [
    '<rootDir>/tests/ts/**/*.test.ts',
    '<rootDir>/tests/ts/**/*.test.tsx'
  ],
  transform: {
    '^.+\\.tsx?$': [
      'ts-jest',
      {
        tsconfig: '<rootDir>/tests/ts/tsconfig.json'
      }
    ]
  },
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json'],
  // tiktoken pulls in WebAssembly that doesn't load cleanly under jsdom.
  // The tests don't depend on real tokenization, so stub it out.
  moduleNameMapper: {
    '^tiktoken$': '<rootDir>/tests/ts/__mocks__/tiktoken.ts',
    '\\.svg$': '<rootDir>/tests/ts/__mocks__/svg.ts',
    '^@jupyterlab/apputils$':
      '<rootDir>/tests/ts/__mocks__/jupyterlab-apputils.ts',
    '^@jupyterlab/filebrowser$':
      '<rootDir>/tests/ts/__mocks__/jupyterlab-filebrowser.ts'
  },
  clearMocks: true
};
