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
    ],
    '^.+\\.jsx?$': [
      'ts-jest',
      {
        tsconfig: {
          allowJs: true,
          esModuleInterop: true,
          isolatedModules: true,
          jsx: 'react',
          module: 'commonjs',
          target: 'ES2018'
        }
      }
    ]
  },
  // Exercise the real Markdown parser and plugins in integration tests.
  // Their ESM-only dependencies need transforming in Jest's CommonJS runner.
  transformIgnorePatterns: [
    '/node_modules/(?!(' +
      [
        'react-markdown',
        'remark-[^/]+',
        'unified',
        'hast-util-[^/]+',
        'mdast-util-[^/]+',
        'micromark(?:-[^/]+)?',
        'unist-util-[^/]+',
        'vfile(?:-[^/]+)?',
        'character-[^/]+',
        'decode-named-character-reference',
        'estree-util-is-identifier-name',
        'escape-string-regexp',
        'comma-separated-tokens',
        'space-separated-tokens',
        'html-url-attributes',
        'is-alphabetical',
        'is-alphanumerical',
        'is-decimal',
        'is-hexadecimal',
        'is-plain-obj',
        'longest-streak',
        'markdown-table',
        'parse-entities',
        'property-information',
        'stringify-entities',
        'trim-lines',
        'bail',
        'ccount',
        'devlop',
        'trough',
        'zwitch',
        '@ungap/structured-clone'
      ].join('|') +
      ')(?:/|$))'
  ],
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json'],
  // tiktoken pulls in WebAssembly that doesn't load cleanly under jsdom.
  // The tests don't depend on real tokenization, so stub it out.
  moduleNameMapper: {
    '^tiktoken$': '<rootDir>/tests/ts/__mocks__/tiktoken.ts',
    '^strip-ansi$': '<rootDir>/tests/ts/__mocks__/strip-ansi.ts',
    '\\.svg$': '<rootDir>/tests/ts/__mocks__/svg.ts',
    '^@jupyterlab/apputils$':
      '<rootDir>/tests/ts/__mocks__/jupyterlab-apputils.ts',
    '^@jupyterlab/filebrowser$':
      '<rootDir>/tests/ts/__mocks__/jupyterlab-filebrowser.ts',
    '^@jupyterlab/translation$':
      '<rootDir>/tests/ts/__mocks__/jupyterlab-translation.ts'
  },
  clearMocks: true
};
