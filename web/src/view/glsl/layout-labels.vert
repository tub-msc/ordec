// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

attribute vec4 aVertexPosition;
uniform mat4 uModelViewMatrix;
uniform mat4 uProjectionMatrix;
attribute vec2 aTextureCoord;
attribute vec2 aPixelCoord;

uniform highp vec4 uLayerColor;
uniform highp vec2 uPixelScale;
varying highp vec2 vTextureCoord;

void main() {
    vec4 pos = uProjectionMatrix * uModelViewMatrix * aVertexPosition;
    gl_Position = vec4(
        pos.x + aPixelCoord.x * uPixelScale.x,
        pos.y  - aPixelCoord.y * uPixelScale.y,
        0,
        pos.w
    );
    vTextureCoord = aTextureCoord;
}
