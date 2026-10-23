// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Grid dots; drawn with the fragment shader of the highlight program.

attribute vec4 aVertexPosition;
uniform mat4 uModelViewMatrix;
uniform mat4 uProjectionMatrix;
uniform vec2 uViewport;     // drawing buffer size in pixels [width, height]

void main() {
    vec4 pos = uProjectionMatrix * uModelViewMatrix * aVertexPosition;
    // Dots are drawn onto the (multisampled) canvas: centering them on a
    // pixel corner makes them cover exactly 2x2 pixels, without
    // antialiasing.
    vec2 px = floor((pos.xy / pos.w * 0.5 + 0.5) * uViewport + 0.5);
    gl_Position = vec4(px / uViewport * 2.0 - 1.0, 0.0, 1.0);
    gl_PointSize = 2.0;
}
