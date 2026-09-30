// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Grid dots; drawn with the fragment shader of the shapes program.

attribute vec4 aVertexPosition;
uniform mat4 uModelViewMatrix;
uniform mat4 uProjectionMatrix;

uniform highp vec4 uLayerColor;

void main() {
    vec4 pos = uProjectionMatrix * uModelViewMatrix * aVertexPosition;
    gl_Position = vec4(
        pos.x,
        pos.y,
        uLayerColor.a,
        pos.w
    );
    gl_PointSize = 2.0;
}
