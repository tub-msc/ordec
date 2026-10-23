// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

varying highp vec2 vTextureCoord;
uniform sampler2D uSampler;
// 1.0 on light backgrounds: dark text, drawn with MIN blending.
uniform highp float uInvert;

void main(void) {
    highp vec4 x = texture2D(uSampler, vTextureCoord);
    highp float v = mix(x.r, 1.0 - x.r, uInvert);
    gl_FragColor = vec4(v, v, v, 1.0);
}
