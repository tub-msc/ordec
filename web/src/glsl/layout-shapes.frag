// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

uniform highp vec4 uLayerColor;

uniform highp float uBrightness;

void main() {
    gl_FragColor = vec4(uLayerColor.r * uBrightness, uLayerColor.g * uBrightness, uLayerColor.b * uBrightness, 1.0);
}
