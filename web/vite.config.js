// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import glsl from 'vite-plugin-glsl';

const __dirname = dirname(fileURLToPath(import.meta.url));

// By default, Vite sends "Cache-control: no-cache" with all responses.
// For font preloading with <link> to work, we need to mark the fonts as
// cachable. This is done using the following mini plugin.
// See: https://github.com/vitejs/vite/issues/7888#issuecomment-1689880790
// Note: the preloading <link> is disabled for now.
function enableFontCaching() {
    return {
        name: 'enable-font-caching',
        configureServer(server) {
            server.middlewares.use((req, res, next) => {
                if (req.url?.endsWith('.ttf')) {
                    res.setHeader('Cache-Control', 'max-age=3600')
                }
                next();
            });
        }
    };
}

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
    plugins: [
        glsl(),
        enableFontCaching(),
    ],
});
