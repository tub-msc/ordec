// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

attribute vec4 aVertexPosition;
attribute vec2 aTextureCoord;

uniform mat4 uProjectionMatrix;
varying highp vec2 vTextureCoord;

void main(void) {
    gl_Position = uProjectionMatrix * aVertexPosition;
    vTextureCoord = aTextureCoord;
}
