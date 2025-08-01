// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  server: {
    proxy: {
      '^/api/.*': {
        target: 'ws://127.0.0.1:8100',
        ws: true,
        rewriteWsOrigin: true,
      },
    },
  },
  build: {
    target: 'esnext',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        app: resolve(__dirname, 'app.html'),
      },
    },
  },
  appType: 'mpa', // without this, vite dev returns index.html instead of 404 for files that are not found.
})
