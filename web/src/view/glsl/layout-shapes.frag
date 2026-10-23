// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Writes one layer's contribution to the intermediate float buffer. What is
// written depends on the blend mode (uMode, see BLEND_MODES in
// layout-style.js); layout-post.frag turns the buffer into the final colors.

precision highp float;

uniform int uMode;
uniform vec3 uColor;     // layer color, 0..1
uniform float uGain;     // mode-specific intensity
uniform float uWeight;   // alpha (over mode) or emphasis factor (other modes)

// Fill pattern: uPattern is the index into the pattern atlas, or < 0 for
// solid. Pattern pixel coordinates are screen coordinates * uPatternMul +
// uPatternAdd.
uniform float uPattern;
uniform float uPatternCount;
uniform vec2 uPatternMul;
uniform vec2 uPatternAdd;
uniform sampler2D uPatterns;

void main() {
    // Pixels not set in the pattern are left alone.
    if (uPattern >= 0.0) {
        vec2 p = floor(gl_FragCoord.xy * uPatternMul + uPatternAdd);
        vec2 t = mod(p, 16.0);
        float bit = texture2D(uPatterns, vec2(
            (t.x + 0.5) / 16.0,
            (uPattern * 16.0 + t.y + 0.5) / (16.0 * uPatternCount)
        )).r;
        if (bit < 0.5) {
            discard;
        }
    }
    float w = uWeight;
    vec3 c = uColor;
    if (uMode == 0) {
        // Additive light: optical density of the light, summed per pixel.
        gl_FragColor = vec4(-log(1.0 - 0.95 * c) * uGain * w, 1.0);
    } else if (uMode == 1 || uMode == 2) {
        // Over (premultiplied alpha) or mix (weighted color sum + weight).
        gl_FragColor = vec4(c * w, w);
    } else if (uMode == 3) {
        // Lighten (max blending).
        gl_FragColor = vec4(c * w * uGain, w);
    } else {
        // Ink: absorbance of a filter transmitting c, summed per pixel.
        gl_FragColor = vec4(-log(1.0 - 0.95 * (1.0 - c)) * uGain * w, 1.0);
    }
}
