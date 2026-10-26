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

// SVG viewer for schematics and symbols.
// Listens to lvs:schem-select and lvs:clear for LVS highlighting.
// Also consumes pending 'lvs:select' on init if schematic opened after LVS item selected.
export class SvgView extends View {
    constructor(resContent, viewName, resultViewer, panelContainer) {
        super(resContent, viewName, resultViewer, panelContainer);
        this.transform = d3.zoomIdentity;
        this.tooltip = document.createElement('div');
        this.tooltip.classList.add('schem-error-tooltip');
        this.coordsDisplay = new CoordinateDisplay();
        this.highlightOverlay = null;
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

        // Find the inner transformed group (with Y-flip) to append highlight in same coordinate space
        const innerGroup = this.g.select('g[transform]');
        if (innerGroup.empty()) {
            return;
        }

        const highlightGroup = innerGroup.append("g")
            .attr("class", "lvs-highlight-group");

        const itemType = data.item_type;
        const schemNid = data.schem_nid;

        if (schemNid === undefined || schemNid === null) {
            highlightGroup.remove();
            return;
        }

        // Select all elements with matching data-nid
        const elements = this.g.selectAll(`[data-nid="${schemNid}"]`);
        if (elements.empty()) {
            highlightGroup.remove();
            return;
        }

        if (itemType === 'device' || itemType === 'subcircuit') {
            // Instance highlighting: draw bounding rect around the instance group
            const instGroup = elements.filter('g');
            if (instGroup.empty()) {
                highlightGroup.remove();
                return;
            }
            const bbox = instGroup.node().getBBox();
            const pad = 0.3;
            highlightGroup.append("rect")
                .attr("class", "lvs-highlight-border")
                .attr("x", bbox.x - pad)
                .attr("y", bbox.y - pad)
                .attr("width", bbox.width + pad * 2)
                .attr("height", bbox.height + pad * 2)
                .attr("rx", 0.5)
                .attr("ry", 0.5)
                .attr("fill", "rgba(255, 0, 0, 0.25)")
                .attr("stroke", "none");
        } else if (itemType === 'net') {
            // Net highlighting: highlight wires and tap points only (not ports)
            elements.each(function() {
                const el = d3.select(this);
                const tagName = this.tagName.toLowerCase();
                if (tagName === 'path') {
                    // Wire/tappoint: draw thicker translucent stroke along the path
                    const pathD = el.attr('d');
                    const transform = el.attr('transform');
                    const pathEl = highlightGroup.append("path")
                        .attr("d", pathD)
                        .attr("fill", "none")
                        .attr("stroke", "rgba(255, 0, 0, 0.4)")
                        .attr("stroke-width", 0.4)
                        .attr("stroke-linecap", "round");
                    if (transform) {
                        pathEl.attr("transform", transform);
                    }
                } else if (tagName === 'circle') {
                    // Connection point: draw larger translucent circle
                    highlightGroup.append("circle")
                        .attr("cx", el.attr('cx'))
                        .attr("cy", el.attr('cy'))
                        .attr("r", 0.5)
                        .attr("fill", "rgba(255, 0, 0, 0.25)")
                        .attr("stroke", "none");
                }
                // Skip 'g' elements (ports) - only highlight wires and connection points
            });
        } else if (itemType === 'pin') {
            // Pin highlighting: highlight only the port (not the connected wires)
            const portGroup = elements.filter('g');
            if (portGroup.empty()) {
                highlightGroup.remove();
                return;
            }
            // Find the portArrow path and extract position from its transform
            const portArrow = portGroup.select('path.portArrow');
            let cx, cy;
            if (!portArrow.empty()) {
                const transform = portArrow.attr('transform');
                // Parse matrix(a,b,c,d,e,f) where e,f are the translation
                const match = transform && transform.match(/matrix\(([^)]+)\)/);
                if (match) {
                    const vals = match[1].split(/[\s,]+/).map(parseFloat);
                    cx = vals[4];
                    cy = vals[5];
                }
            }
            if (cx === undefined) {
                // Fallback to bbox center
                const bbox = portGroup.node().getBBox();
                cx = bbox.x + bbox.width / 2;
                cy = bbox.y + bbox.height / 2;
            }
            highlightGroup.append("circle")
                .attr("cx", cx)
                .attr("cy", cy)
                .attr("r", 0.5)
                .attr("fill", "rgba(255, 0, 0, 0.25)")
                .attr("stroke", "none");
        } else {
            // Unknown item type, remove empty group
            highlightGroup.remove();
            return;
        }

        this.highlightOverlay = highlightGroup;
    }
    clearHighlight() {
        if (this.highlightOverlay) {
            this.highlightOverlay.remove();
            this.highlightOverlay = null;
        }
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
        this.crossingWires = msgData.crossing_select ? findCrossings(this.svgNode) : [];
        if (msgData.crossing_select) {
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
            statusBar.append(crossingSelect);
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
        svg.on('mouseleave', () => this.coordsDisplay.clear());

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
        // element; capture the bus here since `this` is not the view inside.
        const eventBus = this.eventBus;
        this.g.selectAll('g[data-srcline]')
            .style('cursor', 'pointer')
            .on('click', function(event) {
                event.stopPropagation();
                const el = d3.select(this);
                const line = parseInt(el.attr('data-srcline'), 10);
                const column = parseInt(el.attr('data-srccol'), 10);
                const file = el.attr('data-srcfile');
                if (!Number.isNaN(line)) {
                    eventBus.emit('editor:goto-source', { file, line, column });
                }
            });

        const pending = this.takePendingSelection('pendingHighlight');
        if (pending) {
            this.setHighlight(pending);
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
        this.clearHighlight();
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
    }
}
