// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

attribute vec2 aVertexPosition;
// Per-instance placement transform, as the two rows of the affine matrix:
// x' = dot(aTransformX, (x, y, 1)), y' = dot(aTransformY, (x, y, 1)).
attribute vec3 aTransformX;
attribute vec3 aTransformY;
uniform mat4 uProjectionMatrix;

uniform highp vec4 uLayerColor;

void main() {
    vec3 p = vec3(aVertexPosition, 1.0);
    vec4 pos = uProjectionMatrix * vec4(dot(aTransformX, p), dot(aTransformY, p), 0.0, 1.0);
    gl_Position = vec4(
        pos.x,
        pos.y,
        uLayerColor.a,
        pos.w
    );
}
