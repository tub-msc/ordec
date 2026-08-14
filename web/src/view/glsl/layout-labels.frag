// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

varying highp vec2 vTextureCoord;
uniform sampler2D uSampler;

void main(void) {
    highp vec4 x = texture2D(uSampler, vTextureCoord);
    //gl_FragColor = vec4(100, 0, 0, 1.0);
    gl_FragColor = vec4(x.r, x.r, x.r, 1.0);
}
