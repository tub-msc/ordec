// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Vite dev server run by ordec in editable installations (see
// src/ordec/vite.py). It listens on a Unix domain socket instead of a TCP
// port; ordec forwards HTTP requests and HMR websocket connections to it.
// The Vite CLI cannot listen on a socket, hence Vite's middleware mode with
// an own HTTP server.
//
// Usage: node dev-server.mjs SOCKET_PATH BASE_PATH

import http from 'node:http';
import { createServer } from 'vite';

const [socketPath, base] = process.argv.slice(2);

const httpServer = http.createServer();
const vite = await createServer({
    base,
    // Info messages log every hot update; warnings and errors (e.g. syntax
    // errors in frontend code) are the ones of interest.
    logLevel: 'warn',
    clearScreen: false,
    server: {
        middlewareMode: true,
        hmr: { server: httpServer },
    },
});
httpServer.on('request', vite.middlewares);
httpServer.listen(socketPath);

// ordec holds the other end of stdin: exit with ordec, even if ordec is
// killed.
process.stdin.on('end', () => process.exit());
process.stdin.resume();
