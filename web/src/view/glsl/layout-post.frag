// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Turns the intermediate float buffer (see layout-shapes.frag) into colors,
// on background uBg.

precision highp float;

varying vec2 vTextureCoord;

uniform sampler2D uSampler;
uniform int uMode;
uniform vec3 uBg;
uniform float uGain;

void main(void) {
    vec4 x = texture2D(uSampler, vTextureCoord);
    vec3 o;
    if (uMode == 0) {
        // Additive light (on black: 1 - exp(-x)).
        o = 1.0 - (1.0 - uBg) * exp(-x.rgb);
    } else if (uMode == 2) {
        // Mix: average color, coverage from the summed weight.
        vec3 avg = x.a > 0.0 ? x.rgb / x.a : vec3(0.0);
        o = mix(uBg, avg, 1.0 - exp(-x.a * uGain));
    } else if (uMode == 4) {
        // Ink: transmitted background light.
        o = uBg * exp(-x.rgb);
    } else {
        // Over / lighten: premultiplied color over the background.
        o = x.rgb + uBg * (1.0 - min(x.a, 1.0));
    }
    gl_FragColor = vec4(clamp(o, 0.0, 1.0), 1.0);
}
