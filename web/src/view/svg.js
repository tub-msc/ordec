// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import * as d3 from "d3";
import { View, CoordinateDisplay } from './view.js';

const CROSSING_TITLE = 'How wires crossing without connection are drawn (saved for all schematics)';

// Crossing styles: value of the schematic.crossings setting (see
// src/ordec/config.py) -> label.
const CROSSING_STYLES = new Map([
    ['plain', 'plain'],
    ['bridge-h', 'bridge horizontal'],
    ['bridge-v', 'bridge vertical'],
    ['gap-h', 'gap horizontal'],
    ['gap-v', 'gap vertical'],
]);
const CROSSING_RADIUS = 0.25;

// Wire crossings are a concern of the viewer only: render.py draws the wires
// plain, and the viewer finds their crossings in the SVG and redraws the
// wires with crossings in the style of the user's configuration.

// Vertices of a wire path, as written by svg_path (MixinPolygonalChain in
// src/ordec/core/schema/base.py): "Mx y Lx y ...", with "Z" if closed.
function pathVertices(d) {
    const vertices = [...d.matchAll(/[ML](\S+) (\S+)/g)].map(m => [Number(m[1]), Number(m[2])]);
    if (d.endsWith('Z')) {
        vertices.push(vertices[0]);
    }
    return vertices;
}

// Whether point p lies strictly inside the horizontal or vertical segment a-b.
function inside(p, a, b) {
    return [0, 1].some(k => a[1 - k] == b[1 - k] && p[1 - k] == a[1 - k]
        && (p[k] - a[k]) * (p[k] - b[k]) < 0);
}

// Drops the vertices that lie in the middle of a straight run, e.g. the stub
// vertex the router places next to a pin. Without this, a crossing at such a
// vertex is not passed through by either of its segments.
function pruneCollinear(vertices) {
    const pruned = vertices.slice(0, 1);
    for (let i = 1; i < vertices.length - 1; i++) {
        if (!inside(vertices[i], pruned.at(-1), vertices[i + 1])) {
            pruned.push(vertices[i]);
        }
    }
    if (vertices.length > 1) {
        pruned.push(vertices.at(-1));
    }
    return pruned;
}

// Finds the crossings of a schematic's wires: points where a horizontal and
// a vertical segment pass through each other (neither ending there) without
// connPoint. Returns the wires that have crossings, as {path, d, vertices,
// crossings}.
function findCrossings(svgNode) {
    const connPoints = new Set([...svgNode.querySelectorAll('circle.connPoint')].map(c =>
        `${[Number(c.getAttribute('cx')), Number(c.getAttribute('cy'))]}`));
    const wires = [...svgNode.querySelectorAll('path.schemWire')].map(path => {
        const d = path.getAttribute('d');
        return {path, d, vertices: pruneCollinear(pathVertices(d)), crossings: []};
    });
    const segments = wires.flatMap(wire =>
        wire.vertices.slice(1).map((b, i) => [wire, wire.vertices[i], b]));
    const horizontal = segments.filter(([, a, b]) => a[1] == b[1] && a[0] != b[0]);
    const vertical = segments.filter(([, a, b]) => a[0] == b[0] && a[1] != b[1]);
    for (const [hwire, ha, hb] of horizontal) {
        for (const [vwire, va, vb] of vertical) {
            const p = [va[0], ha[1]];
            if (inside(p, ha, hb) && inside(p, va, vb) && !connPoints.has(`${p}`)) {
                hwire.crossings.push(p);
                vwire.crossings.push(p);
            }
        }
    }
    return wires.filter(wire => wire.crossings.length);
}

// Draws a wire of findCrossings in the given style: 'plain' as rendered,
// the others interrupt the horizontal ('-h') or vertical ('-v') segment at
// each crossing, with a half circle bulging up or right ('bridge-') or
// nothing ('gap-').
function drawCrossings(wire, style) {
    const [kind, orient] = style.split('-');
    if (kind != 'bridge' && kind != 'gap') {
        wire.path.setAttribute('d', wire.d);
        return;
    }
    const r = CROSSING_RADIUS;
    const vertices = wire.vertices;
    const d = [`M${vertices[0].join(' ')}`];
    for (let i = 1; i < vertices.length; i++) {
        const [a, b] = [vertices[i - 1], vertices[i]];
        const vertical = a[0] == b[0];
        if (orient == (vertical ? 'v' : 'h')) {
            // (u, w): coordinate along and across the segment.
            const uw = ([x, y]) => vertical ? [y, x] : [x, y];
            const xy = (u, w) => vertical ? `${w} ${u}` : `${u} ${w}`;
            const [[ua, w], [ub]] = [uw(a), uw(b)];
            const step = Math.sign(ub - ua);
            // Sweep flag 1 is counterclockwise in schematic coordinates (y up,
            // see setup_canvas in render.py): bulging up when going right is
            // clockwise, bulging right when going up is counterclockwise.
            const sweep = (vertical == (step > 0)) ? 1 : 0;
            // Crossings in the order the segment passes them; a wire crossing
            // itself has the same one twice.
            const us = [...new Set(wire.crossings.filter(c => inside(c, a, b)).map(c => uw(c)[0]))]
                .sort((u1, u2) => step * (u1 - u2));
            for (const u of us) {
                d.push(`L${xy(u - step * r, w)}`);
                const end = xy(u + step * r, w);
                d.push(kind == 'bridge' ? `A${r} ${r} 0 0 ${sweep} ${end}` : `M${end}`);
            }
        }
        d.push(`L${b.join(' ')}`);
    }
    wire.path.setAttribute('d', d.join(' '));
}

// Selection of schematics (not symbols): the nets and instances of a
// schematic are selectable. render.py marks the wires, junctions, tap points
// (with their labels) and ports with the nid of their net, and the instance
// groups with the nid of the instance (data-nid). mark highlights such
// elements by marking them with a class and drawing a halo beneath them, for
// two independent users: the selectable under the pointer ("markHover") and
// the net, pin (port only) or instance of an LVS selection ("markLvs", see
// setHighlight). The class sets the color (see style.css); where both mark
// an element, it is red with the hover halo. Hovering a selectable
// highlights it and shows its name (from the selectable names of the view
// data) in the status bar. The hover highlight appears after HOVER_DELAY,
// so that sweeping the pointer across the schematic does not flash what it
// passes; it disappears right away. A click pins the highlight, like the
// focus of report plots: until the selectable is clicked again, something
// else is clicked or Escape is pressed (see the document listeners below the
// class), hovering does not change it. At most one selectable is pinned, in
// any viewer. Pinning an instance also jumps to its source (click-to-source),
// releasing it does not. As the wires are thin, wide invisible copies of the
// wires and tap points ("netHit") serve as their hit area, beneath all other
// elements, so that the instances (hit area: their outline rect) still get
// their clicks. The copies carry the nid as data-net instead of data-nid, so
// that they do not show up in the LVS highlight.
const HOVER_DELAY = 80; // ms

// SVG viewer for schematics and symbols.
// Listens to lvs:schem-select and lvs:clear for LVS highlighting.
// Also consumes pending 'lvs:select' on init if schematic opened after LVS item selected.
export class SvgView extends View {
    // The viewer with the pinned selectable (see setPinned), at most one.
    static pinned = null;

    constructor(resContent, viewName, resultViewer, panelContainer) {
        super(resContent, viewName, resultViewer, panelContainer);
        this.transform = d3.zoomIdentity;
        this.tooltip = document.createElement('div');
        this.tooltip.classList.add('schem-error-tooltip');
        this.coordsDisplay = new CoordinateDisplay();
        // The data of the shown highlight, redrawn on crossing style changes.
        this.highlightData = null;
        this.svg = null;
        this.baseTransform = null;
        this.resizeObserver = null;
        // Details toggle, kept across updates: off hides the grid and the pin
        // labels that symbols mark as hidden (class "detailOnly" in render.py),
        // on shows them.
        this.detail = false;
        // Crossing style select of schematics (null for symbols).
        this.crossingSelect = null;
        // The wires with crossings (see findCrossings).
        this.crossingWires = [];
        // Selection (see setupSelection): the names of the selectables by
        // nid, the halo groups by marking class (see mark), the status bar
        // element with the name, the nid of the hover-highlighted selectable
        // and of the selectable under the pointer, and the timeout of hover.
        this.selectable = new Map();
        this.halos = new Map();
        this.selectionDisplay = null;
        this.shown = null;
        this.hovered = null;
        this.hoverTimeout = null;

        this.onLvsSelect = (data) => {
            if (data && !this.selectionApplies(data.schemView, data.schemWireHash)) {
                return;
            }
            this.setHighlight(data);
        };
        this.onLvsClear = () => this.clearHighlight();
        this.busSubscribe('lvs:schem-select', this.onLvsSelect);
        this.busSubscribe('lvs:clear', this.onLvsClear);
        // The crossing style is global: a change in any viewer applies to all.
        this.busSubscribe('config:change', () => {
            this.applyCrossings();
            // The highlight copies the wire paths.
            if (this.highlightData) {
                this.setHighlight(this.highlightData);
            }
        });

        // A selection made before this view was opened; taken by update(),
        // once there is an SVG to highlight in and a wire hash to match.
        this.pendingHighlight = this.eventBus.getPending('lvs:select') || null;
    }
    pendingApplies(pending) {
        return this.selectionApplies(pending.schemView, pending.schemWireHash);
    }
    zoomed({transform}) {
        this.transform = transform;
        this.g.attr("transform", transform);
    }
    sameTransform(a, b) {
        return a && b && Math.abs(a.k - b.k) < 1e-9
            && Math.abs(a.x - b.x) < 1e-6
            && Math.abs(a.y - b.y) < 1e-6;
    }
    // Computes the base (zoomed-out) transform: fit to the panel, but
    // never enlarged beyond the nominal rendered size; smaller-than-
    // panel content is centered. Re-applied whenever the view is at
    // the base, so the cap follows panel resizes; a user zoom is left
    // untouched.
    updateBaseTransform() {
        const rect = this.svgNode.getBoundingClientRect();
        if (!rect.width || !rect.height) {
            return;
        }
        const [vx, vy, vw, vh] = this.viewbox;
        const fitScale = Math.min(rect.width / vw, rect.height / vh);
        const k = Math.min(1, this.nominalScale / fitScale);
        const base = d3.zoomIdentity
            .translate((vx + vw / 2) * (1 - k), (vy + vh / 2) * (1 - k))
            .scale(k);
        const wasAtBase = this.baseTransform
            ? this.sameTransform(this.transform, this.baseTransform)
            : this.sameTransform(this.transform, d3.zoomIdentity);
        this.zoom.scaleExtent([k, 12]);
        this.baseTransform = base;
        if (wasAtBase && !this.sameTransform(this.transform, base)) {
            this.svg.call(this.zoom.transform, base);
        }
    }
    setHighlight(data) {
        this.clearHighlight();
        this.highlightData = data;
        if (!this.svg) {
            return;
        }

        const itemType = data.item_type;
        const schemNid = data.schem_nid;

        if (schemNid === undefined || schemNid === null) {
            return;
        }
        // The elements of the net, or the instance group.
        const elements = [...this.svgNode.querySelectorAll(`[data-nid="${schemNid}"]`)];
        if (itemType === 'pin') {
            // Only the port: it carries the nid of its net, like the wires.
            this.mark('markLvs', elements.filter(el => el.matches('g')));
        } else if (['net', 'device', 'subcircuit'].includes(itemType)) {
            this.mark('markLvs', elements);
        }
    }
    clearHighlight() {
        this.mark('markLvs', []);
        this.highlightData = null;
    }
    update(msgData, wireHash) {
        // The highlight belongs to the replaced SVG.
        this.clearHighlight();
        this.wireHash = wireHash;
        const viewbox = msgData['viewbox'];
        const [vx, vy, vw, vh] = viewbox;
        const zoomExtent = [[vx, vy], [vx + vw, vy + vh]];
        // Convert SVG Y coordinates back to schematic Y coordinates.
        const yFlipOffset = 2 * vy + vh;

        const svg = d3.create("svg")
            .attr("class", "fit schem-svg")
            .attr("viewBox", viewbox);
        this.svg = svg;

        this.g = svg.append("g")
            .html(msgData['inner'])

        // The svg fills the panel; the base zoom transform caps the
        // resting view at the nominal rendered size and centers it
        // (see updateBaseTransform). Zooming in from there can use
        // the full panel.
        this.viewbox = viewbox;
        this.nominalScale = parseFloat(msgData.width) / vw;

        this.zoom = d3.zoom()
            .extent(zoomExtent)
            .scaleExtent([1, 12])
            .translateExtent(zoomExtent);

        svg.call(this.zoom.transform, this.transform);
        this.g.attr("transform", this.transform);

        svg.call(this.zoom.on("zoom", (x) => this.zoomed(x)));

        this.svgNode = svg.node();

        const schemRoot = document.createElement('div');
        schemRoot.className = 'schem-viewer';

        const svgHost = document.createElement('div');
        svgHost.className = 'schem-canvas';
        svgHost.append(this.svgNode, this.tooltip);

        const statusBar = document.createElement('div');
        statusBar.className = 'viewer-statusbar schem-statusbar';
        const detailToggle = document.createElement('button');
        detailToggle.type = 'button';
        detailToggle.className = 'schem-detail-toggle';
        detailToggle.title = 'Show the grid and the pin names hidden by symbols';
        const applyDetail = () => {
            this.svgNode.classList.toggle('schem-detail', this.detail);
            detailToggle.classList.toggle('active', this.detail);
            detailToggle.textContent = `Details: ${this.detail ? 'on' : 'off'}`;
        };
        detailToggle.onclick = () => {
            this.detail = !this.detail;
            applyDetail();
        };
        applyDetail();
        statusBar.append(detailToggle);
        this.crossingSelect = null;
        this.crossingWires = msgData.is_schematic ? findCrossings(this.svgNode) : [];
        // Before applyCrossings, so that the hit area copies the plain wires.
        this.setupSelection(msgData.is_schematic, msgData.selectable);
        if (msgData.is_schematic) {
            const crossingSelect = document.createElement('select');
            crossingSelect.className = 'schem-crossing-select';
            for (const [value, label] of CROSSING_STYLES) {
                crossingSelect.add(new Option(`Crossings: ${label}`, value));
            }
            crossingSelect.onchange = () => {
                this.resultViewer.client.setConfig('schematic', 'crossings', crossingSelect.value, exception => {
                    crossingSelect.classList.toggle('error', !!exception);
                    crossingSelect.title = exception ? `Not saved: ${exception.message}` : CROSSING_TITLE;
                });
            };
            crossingSelect.title = CROSSING_TITLE;
            statusBar.append(crossingSelect, this.selectionDisplay);
            this.crossingSelect = crossingSelect;
        }
        this.applyCrossings();
        statusBar.append(this.coordsDisplay.element);
        schemRoot.append(svgHost, statusBar);

        svg.on('mousemove', (event) => {
            const screenCtm = this.svgNode.getScreenCTM();
            if (!screenCtm) {
                this.coordsDisplay.clear();
                return;
            }

            const svgPt = new DOMPoint(event.clientX, event.clientY)
                .matrixTransform(screenCtm.inverse());
            const [x, ySvg] = this.transform.invert([svgPt.x, svgPt.y]);
            const y = yFlipOffset - ySvg;

            if (x < vx || x > vx + vw || y < vy || y > vy + vh) {
                this.coordsDisplay.clear();
                return;
            }

            this.coordsDisplay.set(Math.round(x), Math.round(y));
        });
        svg.on('mouseleave', () => {
            this.coordsDisplay.clear();
            if (SvgView.pinned !== this) {
                this.hover(null);
            }
        });
        svg.on('mouseover', (event) => {
            if (SvgView.pinned !== this) {
                this.hover(this.selectableAt(event.target));
            }
        });
        // Capturing, as instances stop the propagation of their clicks
        // (click-to-source below). d3-zoom suppresses the click after a pan.
        this.svgNode.addEventListener('click', (event) => {
            const nid = this.selectableAt(event.target);
            const pin = nid !== null && !(SvgView.pinned === this && nid === this.shown);
            this.hovered = nid;
            this.show(nid);
            this.setPinned(pin);
        }, true);

        this.resContent.replaceChildren(schemRoot);
        this.coordsDisplay.clear();

        // The base transform depends on the panel size, so it is set
        // once the svg is laid out and tracked across panel resizes.
        // Undebounced on purpose: ResizeObserver fires after layout but
        // before paint, so a synchronous update keeps the resting view
        // pinned at nominal size throughout a resize.
        this.updateBaseTransform();
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }
        this.resizeObserver = new ResizeObserver(
            () => this.updateBaseTransform());
        this.resizeObserver.observe(this.svgNode);

        svg.selectAll('.errorMarker')
            .on('mouseover', (event) => {
                const msg = event.target.getAttribute('data-error');
                this.tooltip.textContent = msg;
                this.tooltip.style.display = 'block';
            })
            .on('mousemove', (event) => {
                const rect = svgHost.getBoundingClientRect();
                this.tooltip.style.left = (event.clientX - rect.left + 10) + 'px';
                this.tooltip.style.top = (event.clientY - rect.top + 10) + 'px';
            })
            .on('mouseout', () => {
                this.tooltip.style.display = 'none';
            });

        // Click-to-source: emit the instance's data-srcline/data-srccol/
        // data-srcfile set in render.py. main.js owns the editor and jumps.
        // The handler is a plain function so d3 binds `this` to the clicked
        // element; capture the view here since `this` is not the view inside.
        // Only the click that pins the instance jumps, not the one that
        // releases it (the capturing click listener above runs first).
        const view = this;
        this.g.selectAll('g[data-srcline]')
            .style('cursor', 'pointer')
            .on('click', function(event) {
                event.stopPropagation();
                if (SvgView.pinned !== view) {
                    return;
                }
                const el = d3.select(this);
                const line = parseInt(el.attr('data-srcline'), 10);
                const column = parseInt(el.attr('data-srccol'), 10);
                const file = el.attr('data-srcfile');
                if (!Number.isNaN(line)) {
                    view.eventBus.emit('editor:goto-source', { file, line, column });
                }
            });

        const pending = this.takePendingSelection('pendingHighlight');
        if (pending) {
            this.setHighlight(pending);
        }
    }
    // Adds the hit area and halo groups of the selection (see above) to a
    // new SVG; symbols get none.
    setupSelection(isSchematic, selectable) {
        this.setPinned(false);
        this.selectable = new Map();
        this.halos = new Map();
        this.selectionDisplay = null;
        this.shown = null;
        this.hovered = null;
        clearTimeout(this.hoverTimeout);
        if (!isSchematic) {
            return;
        }
        this.selectable = new Map(Object.entries(selectable));
        this.selectionDisplay = document.createElement('span');
        this.selectionDisplay.className = 'schem-selection';
        this.selectionDisplay.textContent = 'selection=-';
        // Makes the outline rect of all instances a hit area (see style.css).
        this.svgNode.classList.add('schem-selectable');
        const inner = this.svgNode.querySelector('g.schematic');
        const back = document.createElementNS(inner.namespaceURI, 'g');
        for (const el of inner.querySelectorAll('.schemWire, .tapPoint')) {
            const hit = el.cloneNode();
            hit.setAttribute('class', 'netHit');
            hit.dataset.net = hit.dataset.nid;
            delete hit.dataset.nid;
            back.append(hit);
        }
        // The hover halo above the LVS halo, like the colors.
        for (const cls of ['markLvs', 'markHover']) {
            const halo = document.createElementNS(inner.namespaceURI, 'g');
            halo.setAttribute('class', `markHalo ${cls}`);
            back.append(halo);
            this.halos.set(cls, halo);
        }
        // Right above the grid (the first child, if drawn).
        inner.insertBefore(back, inner.querySelector(':scope > :not(.grid)'));
    }
    // The nid of the selectable that element el belongs to, or null.
    selectableAt(el) {
        const owner = el.closest('[data-nid], [data-net]');
        const nid = owner?.dataset.net ?? owner?.dataset.nid;
        return this.selectable.has(nid) ? nid : null;
    }
    // Pins the shown selectable, or releases it.
    setPinned(pin) {
        if (pin) {
            if (SvgView.pinned !== this) {
                SvgView.pinned?.release();
            }
            SvgView.pinned = this;
        } else if (SvgView.pinned === this) {
            SvgView.pinned = null;
        }
    }
    // Releases the pinned selectable and removes its highlight.
    release() {
        this.setPinned(false);
        this.hovered = null;
        this.show(null);
    }
    // Highlights the selectable under the pointer (nid or null) after
    // HOVER_DELAY, removes the highlight right away (see above).
    hover(nid) {
        if (nid === this.hovered) {
            return;
        }
        this.hovered = nid;
        clearTimeout(this.hoverTimeout);
        if (nid === null || nid === this.shown) {
            this.show(nid);
        } else {
            this.hoverTimeout = setTimeout(() => this.show(nid), HOVER_DELAY);
        }
    }
    // Hover-highlights the selectable of the given nid, or none for null,
    // right away.
    show(nid) {
        clearTimeout(this.hoverTimeout);
        if (nid === this.shown) {
            return;
        }
        this.shown = nid;
        this.selectionDisplay.textContent = `selection=${nid === null ? '-' : this.selectable.get(nid)}`;
        this.mark('markHover', nid === null ? [] : this.svgNode.querySelectorAll(`[data-nid="${nid}"]`));
    }
    // Highlights the given elements (with data-nid) with marking class cls
    // ('markHover' or 'markLvs', see above), replacing the elements it
    // highlighted before; no elements remove the highlight.
    mark(cls, elements) {
        const halo = this.halos.get(cls);
        if (!halo) {
            return; // no SVG yet, or a symbol
        }
        // [data-nid] leaves out the halo group, which has the class too.
        this.svgNode.querySelectorAll(`[data-nid].${cls}`).forEach(el => el.classList.remove(cls));
        halo.replaceChildren();
        for (const el of elements) {
            el.classList.add(cls);
            // The halo follows the current shape of the wires (crossings).
            // Ports and instances (groups) get it for their arrow and lines;
            // junctions and labels get none, as it would only add clutter.
            const shapes = el.matches('g') ? el.querySelectorAll('.portArrow, .symbolPoly') : [el];
            for (const shape of shapes) {
                if (!shape.matches('text, .connPoint')) {
                    const shapeHalo = shape.cloneNode();
                    shapeHalo.removeAttribute('class');
                    delete shapeHalo.dataset.nid;
                    halo.append(shapeHalo);
                }
            }
        }
    }
    // Draws the crossings in the style of the user's configuration ('plain'
    // if unset or unknown).
    applyCrossings() {
        let style = this.resultViewer.client.config.schematic?.crossings;
        if (!CROSSING_STYLES.has(style)) {
            style = 'plain';
        }
        this.crossingWires.forEach(wire => drawCrossings(wire, style));
        if (this.crossingSelect) {
            this.crossingSelect.value = style;
        }
    }
    destroy() {
        this.busUnsubscribeAll();
        this.setPinned(false);
        clearTimeout(this.hoverTimeout);
        this.clearHighlight();
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
    }
}

document.addEventListener('pointerdown', (event) => {
    if (SvgView.pinned && !SvgView.pinned.svgNode.contains(event.target)) {
        SvgView.pinned.release();
    }
}, true);
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        SvgView.pinned?.release();
    }
});
