// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Expands line segments into screen-space quads so highlight outlines can be
// drawn with a constant pixel width independent of zoom. WebGL's gl.lineWidth
// is effectively clamped to 1px on most platforms, so thicker lines have to be
// built from triangles instead.
//
// Each line segment is drawn as two triangles (6 vertices). Every vertex of the
// quad carries the same segment endpoints (aSegStart/aSegEnd) plus the endpoint
// it sits on (aPosition) and which side to offset towards (aSide).

attribute vec2 aPosition;   // endpoint this vertex sits on (segment start or end)
attribute vec2 aSegStart;   // segment start point (same for all 6 quad vertices)
attribute vec2 aSegEnd;     // segment end point (same for all 6 quad vertices)
attribute float aSide;      // +1.0 / -1.0: which side of the line to offset to

uniform mat4 uModelViewMatrix;
uniform mat4 uProjectionMatrix;
uniform vec2 uViewport;     // drawing buffer size in pixels [width, height]
uniform float uHalfWidth;   // half the line width in pixels

void main() {
    mat4 mvp = uProjectionMatrix * uModelViewMatrix;
    vec4 clipP = mvp * vec4(aPosition, 0.0, 1.0);
    vec4 clipS = mvp * vec4(aSegStart, 0.0, 1.0);
    vec4 clipE = mvp * vec4(aSegEnd, 0.0, 1.0);

    // Segment direction in pixel space, so the offset width ends up in pixels:
    vec2 halfViewport = uViewport * 0.5;
    vec2 pxS = clipS.xy / clipS.w * halfViewport;
    vec2 pxE = clipE.xy / clipE.w * halfViewport;
    vec2 d = pxE - pxS;
    float len = length(d);
    vec2 dir = len > 0.0 ? d / len : vec2(1.0, 0.0);
    vec2 perp = vec2(-dir.y, dir.x);

    // Offset this endpoint perpendicular to the segment by uHalfWidth pixels.
    // Convert the pixel offset back to clip space by multiplying with clipP.w to
    // undo the perspective divide that follows:
    vec2 ndcOffset = perp * aSide * uHalfWidth / halfViewport;
    gl_Position = vec4(clipP.xy + ndcOffset * clipP.w, 0.0, clipP.w);
}
