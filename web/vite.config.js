// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import { viteStaticCopy } from 'vite-plugin-static-copy'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  build: {
    target: 'esnext',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        app: resolve(__dirname, 'app.html'),
      },
    },
  },
  plugins: [
    viteStaticCopy({
      targets: [
        {
          src: '../ordec/lib/examples/diffpair.ord',
          dest: 'examples/src/',
        },
        {
          src: '../ordec/lib/examples/nand2.ord',
          dest: 'examples/src/',
        },
        {
          src: '../ordec/lib/examples/voltagedivider.ord',
          dest: 'examples/src/',
        },
        {
          src: '../ordec/lib/examples/voltagedivider_py.py',
          dest: 'examples/src/',
        },
      ]
    })
  ],
  appType: 'mpa', // without this, vite dev returns index.html instead of 404 for files that are not found.
})