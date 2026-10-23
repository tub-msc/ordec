// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Layout rendering styles. The look of a layout comes from the LayoutStyle of
// its technology (see src/ordec/layout/style.py), sent with the layout
// webdata together with its defaults. The style panel in the layout viewer
// sidebar and the layer editor change it locally (applyStyleChange) and in
// the user's customization file (via setlayoutstyle, see client.js); the
// viewer preferences (PREF_DEFAULTS) are kept in localStorage.

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
export const isPref = key => key in PREF_DEFAULTS;

// LayoutStyle settings: webdata name (websettings in
// src/ordec/layout/webdata.py) -> TOML name (STYLE_ATTRS in
// src/ordec/layout/style.py).
const STYLE_SETTINGS = {
    background: 'background',
    blend: 'blend',
    opacity: 'opacity',
};
const SETTING_OF_TOML = Object.fromEntries(
    Object.entries(STYLE_SETTINGS).map(([k, toml]) => [toml, k]));

// Used for layouts whose LayerStack has no LayoutStyle (see layerFill for
// their layers); it cannot be customized.
const STYLE_FALLBACK = {
    key: null,
    userFile: null,
    customized: false,
    userSettings: [],
    userLayers: [],
    userFileEphemeral: false,
    background: [0, 0, 0],
    blend: 'additive',
    opacity: 1.0,
    patterns: [],
};

const hex = rgb => '#' + rgb.map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
const unhex = s => [1, 3, 5].map(i => parseInt(s.slice(i, i + 2), 16));

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

// Resets the viewer preferences in style (and in localStorage).
export function resetPrefs(style) {
    Object.assign(style, PREF_DEFAULTS);
    savePrefs(style);
}

const prefsAtDefault = style => Object.keys(PREF_DEFAULTS).every(k => style[k] === PREF_DEFAULTS[k]);

export function savePrefs(style) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(
        Object.fromEntries(Object.keys(PREF_DEFAULTS).map(k => [k, style[k]]))));
}

// Sets style (in place) to the given webdata style (null if none), with the
// stored preferences.
export function applyStyle(style, webStyle) {
    const base = webStyle ? {
        ...webStyle,
        background: webStyle.background.map(v => v / 255),
        default: {...webStyle.default, background: webStyle.default.background.map(v => v / 255)},
    } : STYLE_FALLBACK;
    Object.assign(style, base, loadPrefs());
}

// Applies a change of the customization file (as sent to the server, see
// LayoutView.saveStyle) to style and to the webdata layers, the way the
// server merges the file (apply_customization in src/ordec/layout/style.py):
// a setting or layer entry replaces the current one, null restores the
// default.
export function applyStyleChange(style, layers, settings, entries) {
    const mark = (list, name, set) => {
        const i = list.indexOf(name);
        if (set && i < 0) list.push(name);
        if (!set && i >= 0) list.splice(i, 1);
    };
    for (const [toml, value] of Object.entries(settings)) {
        const k = SETTING_OF_TOML[toml];
        if (value === null) {
            style[k] = style.default[k];
        } else {
            style[k] = k == 'background' ? unhex(value).map(v => v / 255) : value;
        }
        mark(style.userSettings, toml, value !== null);
    }
    // Layers the default style does not have go on top.
    let top = Math.max(-1, ...layers.map(l => l.order ?? -1));
    for (const [path, entry] of Object.entries(entries)) {
        const layer = layers.find(l => l.path == path);
        if (layer && entry === null) {
            Object.assign(layer, layer.default);
        } else if (layer) {
            Object.assign(layer, {
                order: layer.order ?? ++top,
                styleFill: entry.fill ? unhex(entry.fill) : null,
                styleStroke: entry.stroke ? unhex(entry.stroke) : null,
                styleCrossRect: entry.cross ?? false,
                pattern: entry.pattern ?? null,
            });
        }
        mark(style.userLayers, path, entry !== null);
    }
    style.customized = style.userSettings.length > 0 || style.userLayers.length > 0;
}

// The values of the given LayoutStyle settings of style, by TOML name (as
// update_customization in src/ordec/layout/style.py takes them).
export function styleSettings(style, keys) {
    return Object.fromEntries(keys.map(k => [STYLE_SETTINGS[k],
        k == 'background' ? hex(style.background.map(v => v * 255)) : style[k]]));
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

// Chain icons of the link button between fill and outline color.
const LINKED_ICON = `<svg viewBox="0 0 16 16" width="14" height="14" fill="none"
    stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
    <path d="M6.2 9.8l3.6-3.6"/>
    <path d="M7.4 4.6l1.1-1.1a2.6 2.6 0 0 1 3.7 3.7l-1.1 1.1"/>
    <path d="M8.6 11.4l-1.1 1.1a2.6 2.6 0 0 1-3.7-3.7l1.1-1.1"/></svg>`;
const UNLINKED_ICON = `<svg viewBox="0 0 16 16" width="14" height="14" fill="none"
    stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
    <path d="M8.4 3.6l.6-.6a2.6 2.6 0 0 1 3.7 3.7l-.6.6"/>
    <path d="M7.6 12.4l-.6.6a2.6 2.6 0 0 1-3.7-3.7l.6-.6"/>
    <path d="M3 4.5l1.5.4M4.5 3l.4 1.5M13 11.5l-1.5-.4M11.5 13l-.4-1.5"/></svg>`;

// Popup editing the look of a layer: fill and outline color, cross and fill
// pattern. onSave(entry) receives the layer's new entry in the
// customization file, or null to reset the layer to the default style.
export function showLayerEditor(container, anchor, layer, style, onSave) {
    container.querySelector('.layout-layer-editor')?.remove();
    const look = {...layerLook(layer, style), fill: layer.styleFill};
    const editor = document.createElement('div');
    editor.classList.add('layout-layer-editor');
    const close = () => {
        editor.remove();
        document.removeEventListener('mousedown', onOutside, true);
    };
    const onOutside = (e) => {
        if (!editor.contains(e.target)) close();
    };
    const save = () => {
        const entry = {};
        if (look.fill) entry.fill = hex(look.fill);
        if (look.stroke) entry.stroke = hex(look.stroke);
        if (look.cross) entry.cross = true;
        if (look.pattern !== null) entry.pattern = look.pattern;
        onSave(entry);
        drawPatterns();
        reset.disabled = false; // the layer is in the customization file now
    };

    const title = document.createElement('div');
    title.classList.add('layout-layer-editor-title');
    title.textContent = layer.path;
    editor.appendChild(title);

    // Fill / outline: a checkbox (set or not) and the color. A color that is
    // not set shows the other one.
    const colorRow = (label, own, other) => {
        const row = document.createElement('label');
        row.classList.add('layout-style-row');
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.checked = own !== null;
        const color = document.createElement('input');
        color.type = 'color';
        color.value = hex(own ?? other ?? layerFill({...layer, order: null}, style));
        const span = document.createElement('span');
        span.append(check, ` ${label}`);
        row.append(span, color);
        return {row, check, color};
    };
    const fill = colorRow('Fill', look.fill, look.stroke);
    const stroke = colorRow('Outline', look.stroke, look.fill);

    // While fill and outline color are linked, changing one changes both.
    // The link is not stored: the colors count as linked when the editor
    // opens if they are equal.
    let linked = fill.color.value == stroke.color.value;
    const linkRow = document.createElement('div');
    linkRow.classList.add('layout-style-row');
    const link = document.createElement('button');
    link.type = 'button';
    link.classList.add('layout-layer-link');
    linkRow.append(document.createElement('span'), link);
    const showLink = () => {
        link.innerHTML = linked ? LINKED_ICON : UNLINKED_ICON;
        link.classList.toggle('linked', linked);
        link.title = linked
            ? 'Fill and outline color are linked (click to unlink)'
            : 'Fill and outline color are independent (click to link)';
    };
    showLink();

    // Takes the colors of the enabled rows into look.
    const apply = () => {
        look.fill = fill.check.checked ? unhex(fill.color.value) : null;
        look.stroke = stroke.check.checked ? unhex(stroke.color.value) : null;
        save();
    };
    fill.check.onchange = apply;
    stroke.check.onchange = apply;
    fill.color.onchange = () => {
        fill.check.checked = true;
        if (linked) stroke.color.value = fill.color.value;
        apply();
    };
    stroke.color.onchange = () => {
        stroke.check.checked = true;
        if (linked) fill.color.value = stroke.color.value;
        apply();
    };
    link.onclick = () => {
        linked = !linked;
        showLink();
        if (linked && stroke.color.value != fill.color.value) {
            stroke.color.value = fill.color.value;
            apply();
        }
    };
    editor.append(fill.row, linkRow, stroke.row);

    const crossRow = document.createElement('label');
    crossRow.classList.add('layout-style-row');
    const cross = document.createElement('input');
    cross.type = 'checkbox';
    cross.checked = look.cross;
    cross.onchange = () => {
        look.cross = cross.checked;
        save();
    };
    const crossSpan = document.createElement('span');
    crossSpan.append(cross, ' Cross');
    crossRow.append(crossSpan);
    editor.appendChild(crossRow);

    // Pattern choice, shown in the layer's fill color.
    const grid = document.createElement('div');
    grid.classList.add('layout-pattern-grid');
    editor.appendChild(grid);
    const pickStyle = {...style, blend: 'over', opacity: 1.0};
    function drawPatterns() {
        grid.replaceChildren(...[null, ...style.patterns.map(p => p.name)].map(name => {
            const item = document.createElement('canvas');
            item.title = name ?? 'solid';
            drawSwatch(item, {fill: look.fill ?? layerFill({...layer, order: null}, style),
                stroke: null, cross: false, pattern: name}, pickStyle);
            item.classList.toggle('selected', name === look.pattern);
            item.onclick = () => {
                look.pattern = name;
                save();
            };
            return item;
        }));
    }
    drawPatterns();

    const reset = document.createElement('button');
    reset.type = 'button';
    reset.textContent = 'Reset to default';
    reset.disabled = !style.userLayers.includes(layer.path);
    reset.onclick = () => {
        close();
        onSave(null);
    };
    editor.appendChild(reset);

    // Below the swatch, right-aligned with it, but kept inside the container
    // (moved up if there is not enough room below).
    container.appendChild(editor);
    const a = anchor.getBoundingClientRect();
    const c = container.getBoundingClientRect();
    const top = Math.min(a.bottom - c.top + 2, c.height - editor.offsetHeight - 2);
    editor.style.top = `${Math.max(0, top)}px`;
    editor.style.right = `${c.right - a.right}px`;
    document.addEventListener('mousedown', onOutside, true);
}

const CONTROLS = [
    {key: 'blend', label: 'Blend', type: 'select', options: BLEND_MODES},
    {key: 'brightness', label: 'Intensity', type: 'range', min: 1, max: 100, step: 1,
        when: s => s.blend != 'over'},
    {key: 'opacity', label: 'Fill opacity', type: 'range', min: 0.05, max: 1, step: 0.05,
        when: s => s.blend == 'over'},
    {key: 'background', label: 'Background', type: 'color'},
    {key: 'patternAnchor', label: 'Pattern anchor', type: 'select',
        options: [['pan', 'Screen, follows pan'], ['screen', 'Screen, fixed']]},
    {key: 'patternScale', label: 'Pattern pixel', type: 'select',
        options: [[1, '1 px'], [2, '2 px'], [3, '3 px'], [4, '4 px']]},
];


// Builds the style panel. onChange(keys, commit) is called after the
// settings keys of style changed: with commit false while a slider is
// dragged (preview only), true once the change is final. onReset() is called
// by the reset button, which resets the customization file and the viewer
// preferences. Returns {element, sync, setError}; sync() updates the
// controls from style, setError(text) shows (or with null clears) an error.
export function buildStylePanel(style, onChange, onReset) {
    const details = document.createElement('details');
    details.classList.add('layout-style');
    const summary = document.createElement('summary');
    summary.textContent = 'Style';
    details.appendChild(summary);
    const info = document.createElement('div');
    info.classList.add('layout-style-info');
    const warning = document.createElement('div');
    warning.classList.add('layout-style-warning');
    const error = document.createElement('div');
    error.classList.add('layout-style-error');
    details.append(info, warning, error);

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
                onChange([ctl.key], true);
            };
        } else if (ctl.type == 'range') {
            input = document.createElement('input');
            input.type = 'range';
            input.min = ctl.min;
            input.max = ctl.max;
            input.step = ctl.step;
            input.oninput = () => {
                style[ctl.key] = Number(input.value);
                sync();
                onChange([ctl.key], false);
            };
            input.onchange = () => onChange([ctl.key], true);
        } else {
            // Color (RGB 0..1 in style): previewed while picking, like a
            // dragged slider.
            input = document.createElement('input');
            input.type = 'color';
            input.oninput = () => {
                style[ctl.key] = unhex(input.value).map(v => v / 255);
                onChange([ctl.key], false);
            };
            input.onchange = () => onChange([ctl.key], true);
        }
        rows.push({ctl, input, row: addRow(ctl.label, input)});
    });

    const reset = document.createElement('button');
    reset.type = 'button';
    reset.textContent = 'Reset to default';
    reset.onclick = () => onReset();
    details.appendChild(reset);

    function sync() {
        if (style.key === null) {
            info.textContent = 'This layer stack has no LayoutStyle, so it cannot be customized.';
        } else {
            info.textContent = `LayoutStyle '${style.key}' (${style.customized ? 'customized' : 'default'}).` +
                ` Changes are saved to ${style.userFile}.`;
        }
        warning.textContent = style.userFileEphemeral
            ? 'ORDeC runs in a container here: the saved file will be lost sooner or later, ' +
                'e.g. when the container is replaced.'
            : '';
        reset.disabled = !style.customized && prefsAtDefault(style);
        rows.forEach(({ctl, input, row}) => {
            if (ctl.type == 'color') {
                input.value = hex(style[ctl.key].map(v => v * 255));
            } else {
                input.value = style[ctl.key];
            }
            input.disabled = style.key === null && !isPref(ctl.key);
            row.classList.toggle('inactive', ctl.when ? !ctl.when(style) : false);
        });
    }
    function setError(text) {
        error.textContent = text ?? '';
        if (text) {
            details.open = true;
        }
    }
    sync();
    return {element: details, sync, setError};
}
