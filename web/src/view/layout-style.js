// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Layout rendering styles. The look of a layout comes from the LayoutStyle of
// its technology (see src/ordec/layout/style.py), sent with the layout
// webdata. The viewer preferences (PREF_DEFAULTS) of the style panel in the
// layout viewer sidebar are kept in localStorage.

const STORAGE_KEY = 'ordecLayoutPrefs';

// Fill patterns come with the style (LayoutStylePattern in
// src/ordec/core/schema/layout.py) as {name, rows}: 16 rows of 16 bits, top
// first, most significant bit left. A layer's pattern is a name, or null for
// a solid fill.
export const PATTERN_SIZE = 16;

// Whether pixel (x, y) of a pattern repeated over the plane is set; y points
// down (as on screen).
function patternBit(rows, x, y) {
    return (rows[y % PATTERN_SIZE] >> (PATTERN_SIZE - 1 - x % PATTERN_SIZE)) & 1;
}

// All patterns stacked vertically into one R8 texture (16 x 16*N, with room
// for at least one pattern).
export function patternAtlas(patterns) {
    const s = PATTERN_SIZE;
    const data = new Uint8Array(s * s * Math.max(1, patterns.length));
    patterns.forEach((p, i) => {
        for (let y = 0; y < s; y++) {
            for (let x = 0; x < s; x++) {
                data[(i*s + y)*s + x] = patternBit(p.rows, x, y) ? 255 : 0;
            }
        }
    });
    return data;
}

// The index of a blend mode in this list is its uMode value in the shaders.
// The keys are the values of LayoutBlend in src/ordec/core/schema/layout.py.
export const BLEND_MODES = [
    ['additive', 'Additive light'],
    ['over', 'Z-order (over)'],
    ['mix', 'Mix (average)'],
    ['max', 'Lighten (max)'],
    ['ink', 'Ink (subtractive)'],
];

const PREF_DEFAULTS = {
    brightness: 60,
    patternAnchor: 'pan',
    patternScale: 1,
};

// Used for layouts whose LayerStack has no LayoutStyle (see layerFill for
// their layers).
const STYLE_FALLBACK = {
    key: null,
    userFile: null,
    customized: false,
    background: [0, 0, 0],
    blend: 'additive',
    opacity: 1.0,
    patterns: [],
};

function loadPrefs() {
    let stored = {};
    try {
        stored = JSON.parse(localStorage.getItem(STORAGE_KEY)) ?? {};
    } catch (e) {
        // Malformed storage: fall back to defaults.
    }
    const prefs = {...PREF_DEFAULTS, ...stored};
    if (prefs.patternAnchor != 'screen') {
        prefs.patternAnchor = 'pan'; // also replaces the former 'world'
    }
    return prefs;
}

export function savePrefs(style) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(
        Object.fromEntries(Object.keys(PREF_DEFAULTS).map(k => [k, style[k]]))));
}

// Sets style (in place) to the given webdata style (null if none), with the
// stored preferences.
export function applyStyle(style, webStyle) {
    const base = webStyle
        ? {...webStyle, background: webStyle.background.map(v => v / 255)}
        : STYLE_FALLBACK;
    Object.assign(style, base, loadPrefs());
}

export function isLightBackground(style) {
    const [r, g, b] = style.background;
    return 0.3*r + 0.6*g + 0.1*b > 0.5;
}

// Intensity factor from the brightness slider, 1.0 at its default (60).
export function intensity(style) {
    return Math.exp((style.brightness - 60) / 15);
}

// Fill color (0..255) of a layer: its LayoutStyle fill, or for layers the
// LayoutStyle does not style a plain fill in white (black on light
// backgrounds), so that their shapes are visible.
export function layerFill(layer, style) {
    if (layer.order !== null) {
        return layer.styleFill;
    }
    return isLightBackground(style) ? [0, 0, 0] : [255, 255, 255];
}

// Drawing order of the layers, bottom first: the order of the LayoutStyle,
// then the layers it does not style, by nid.
export function layerOrder(layers) {
    const styled = layers.filter(l => l.order !== null).sort((a, b) => a.order - b.order);
    return styled.concat(layers.filter(l => l.order === null));
}

// A layer's look as drawn: {fill, stroke} (RGB 0..255 or null), cross, pattern.
export function layerLook(layer, style) {
    return {
        fill: layerFill(layer, style),
        stroke: layer.styleStroke,
        cross: layer.styleCrossRect,
        pattern: layer.pattern,
    };
}

// Draws a legend swatch (30x15) approximating a layer look (see layerLook) on
// the current background.
export function drawSwatch(canvas, look, style) {
    const w = 30;
    const h = 15;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    const bg = style.background.map(v => v * 255);
    const img = ctx.createImageData(w, h);
    const fill = look.fill;
    const rows = look.pattern === null ? null
        : style.patterns.find(p => p.name == look.pattern).rows;
    const opacity = style.blend == 'over' ? style.opacity : 1;
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            let a = 0;
            if (fill) {
                a = (rows === null || patternBit(rows, x, y)) ? opacity : 0;
            }
            for (let c = 0; c < 3; c++) {
                img.data[4*(y*w + x) + c] = fill ? bg[c] + (fill[c] - bg[c]) * a : bg[c];
            }
            img.data[4*(y*w + x) + 3] = 255;
        }
    }
    ctx.putImageData(img, 0, 0);
    const stroke = look.stroke;
    if (stroke) {
        ctx.strokeStyle = `rgb(${stroke[0]}, ${stroke[1]}, ${stroke[2]})`;
        ctx.lineWidth = 1;
        ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
        if (look.cross) {
            ctx.beginPath();
            ctx.moveTo(0.5, 0.5); ctx.lineTo(w - 0.5, h - 0.5);
            ctx.moveTo(0.5, h - 0.5); ctx.lineTo(w - 0.5, 0.5);
            ctx.stroke();
        }
    }
}

const CONTROLS = [
    {key: 'brightness', label: 'Intensity', type: 'range', min: 1, max: 100, step: 1,
        when: s => s.blend != 'over'},
    {key: 'patternAnchor', label: 'Pattern anchor', type: 'select',
        options: [['pan', 'Screen, follows pan'], ['screen', 'Screen, fixed']]},
    {key: 'patternScale', label: 'Pattern pixel', type: 'select',
        options: [[1, '1 px'], [2, '2 px'], [3, '3 px'], [4, '4 px']]},
];

// Builds the style panel with the viewer preferences. onChange(key) is
// called after style[key] changed. Returns {element, sync}; sync() updates
// the panel from style.
export function buildStylePanel(style, onChange) {
    const details = document.createElement('details');
    details.classList.add('layout-style');
    const summary = document.createElement('summary');
    summary.textContent = 'Style';
    details.appendChild(summary);
    const info = document.createElement('div');
    info.classList.add('layout-style-info');
    details.appendChild(info);

    const rows = [];
    const addRow = (label, input) => {
        const row = document.createElement('label');
        row.classList.add('layout-style-row');
        const span = document.createElement('span');
        span.textContent = label;
        row.append(span, input);
        details.appendChild(row);
        return row;
    };

    CONTROLS.forEach(ctl => {
        let input;
        if (ctl.type == 'select') {
            input = document.createElement('select');
            ctl.options.forEach(([value, text]) => input.add(new Option(text, value)));
            input.onchange = () => {
                style[ctl.key] = typeof style[ctl.key] == 'number' ? Number(input.value) : input.value;
                sync();
                onChange(ctl.key);
            };
        } else {
            input = document.createElement('input');
            input.type = 'range';
            input.min = ctl.min;
            input.max = ctl.max;
            input.step = ctl.step;
            input.oninput = () => {
                style[ctl.key] = Number(input.value);
                onChange(ctl.key);
            };
        }
        rows.push({ctl, input, row: addRow(ctl.label, input)});
    });

    function sync() {
        if (style.key === null) {
            info.textContent = 'This layer stack has no LayoutStyle.';
        } else {
            info.textContent = `LayoutStyle '${style.key}'` +
                (style.customized ? `, customized by ${style.userFile}.` : ' (default).');
        }
        rows.forEach(({ctl, input, row}) => {
            input.value = style[ctl.key];
            row.classList.toggle('inactive', ctl.when ? !ctl.when(style) : false);
        });
    }
    sync();
    return {element: details, sync};
}
