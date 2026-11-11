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

// Set when ordec runs Vite behind its own server (see src/ordec/vite.py):
// the browser loads the frontend through ordec, but connects the HMR
// websocket to Vite directly. ordec holds the other end of stdin, so that
// Vite exits with ordec, even if ordec is killed.
const ordecHmrPort = process.env.ORDEC_HMR_PORT;
if (ordecHmrPort) {
    process.stdin.on('end', () => process.exit());
    process.stdin.resume();
}

export default defineConfig({
    // Relative asset/import paths, so the built app also works when served
    // under a URL path prefix (e.g. /user/<name>/ behind JupyterHub).
    base: './',
    server: {
        hmr: ordecHmrPort ? { clientPort: Number(ordecHmrPort) } : undefined,
        // For 'npm run dev' with 'ordec -b'.
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
