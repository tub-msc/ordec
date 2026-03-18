// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

/// <reference types="vite/client" />

// GLSL shader imports (via vite-plugin-glsl)
declare module '*.vert' {
    const source: string;
    export default source;
}
declare module '*.frag' {
    const source: string;
    export default source;
}
