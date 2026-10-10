// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Schematic CSS is served from the backend (SchematicRenderer.css in render.py)
// rather than bundled as a frontend asset. This keeps a single source of truth
// for the styles used by both standalone SVG export and the web UI, avoids
// duplicating the CSS into every inline SVG in the DOM, and reduces data
// transferred when multiple schematics are open. main.js inserts it into the
// page; course.js embeds it into the schematic pushed to the scoreboard.
export const schematicCss = fetch('api/schematic.css')
    .then(response => response.text());
