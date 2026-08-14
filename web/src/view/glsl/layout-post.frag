// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

varying highp vec2 vTextureCoord;

uniform sampler2D uSampler;

void main(void) {
    highp vec4 x = texture2D(uSampler, vTextureCoord);

    gl_FragColor = vec4(
        1.0-exp(-x.r),
        1.0-exp(-x.g),
        1.0-exp(-x.b),
        1.0
    );
}
