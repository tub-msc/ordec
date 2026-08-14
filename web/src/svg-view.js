// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import * as d3 from "d3";
import { viewEventBus } from './event-bus.js';
import { CoordinateDisplay } from './viewer-coordinates.js';

// SVG viewer for schematics and symbols.
// Listens to lvs:schem-select and lvs:clear for LVS highlighting.
// Also consumes pending 'lvs:select' on init if schematic opened after LVS item selected.
export class SvgView {
    constructor(resContent, viewName, resultViewer, panelContainer) {
        this.resContent = resContent;
        this.viewName = viewName;
        // Wire hash of the subgraph currently shown; set by each update().
        this.wireHash = null;
        this.transform = d3.zoomIdentity;
        this.tooltip = document.createElement('div');
        this.tooltip.classList.add('schem-error-tooltip');
        this.coordsDisplay = new CoordinateDisplay();
        this.highlightOverlay = null;
        this.svg = null;
        this.baseTransform = null;
        this.resizeObserver = null;

        this._onLvsSelect = (data) => {
            if (data && !this._selectionApplies(data)) {
                return;
            }
            this.setHighlight(data);
        };
        this._onLvsClear = () => this.clearHighlight();
        viewEventBus.on('lvs:schem-select', this._onLvsSelect);
        viewEventBus.on('lvs:clear', this._onLvsClear);

        // A selection made before this view was opened; taken by update(),
        // once there is an SVG to highlight in and a wire hash to match.
        this._pendingHighlight = viewEventBus.getPending('lvs:select') || null;
    }
    // A selection payload applies to this viewer when it is untargeted, or
    // when it names this view: by view name, or by the wire hash of a viewer
    // showing the same subgraph under a different view name.
    _selectionApplies(data) {
        if (!data.schemView) return true;
        if (data.schemView === this.viewName) return true;
        return Boolean(data.schemWireHash && data.schemWireHash === this.wireHash);
    }
    zoomed({transform}) {
        this.transform = transform;
        this.g.attr("transform", transform);
    }
    _sameTransform(a, b) {
        return a && b && Math.abs(a.k - b.k) < 1e-9
            && Math.abs(a.x - b.x) < 1e-6
            && Math.abs(a.y - b.y) < 1e-6;
    }
    // Computes the base (zoomed-out) transform: fit to the panel, but
    // never enlarged beyond the nominal rendered size; smaller-than-
    // panel content is centered. Re-applied whenever the view is at
    // the base, so the cap follows panel resizes; a user zoom is left
    // untouched.
    _updateBaseTransform() {
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
            ? this._sameTransform(this.transform, this.baseTransform)
            : this._sameTransform(this.transform, d3.zoomIdentity);
        this.zoom.scaleExtent([k, 12]);
        this.baseTransform = base;
        if (wasAtBase && !this._sameTransform(this.transform, base)) {
            this.svg.call(this.zoom.transform, base);
        }
    }
    setHighlight(data) {
        this.clearHighlight();
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
    }
    update(msgData, wireHash) {
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
        // (see _updateBaseTransform). Zooming in from there can use
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
        statusBar.appendChild(this.coordsDisplay.element);
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
        this._updateBaseTransform();
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }
        this.resizeObserver = new ResizeObserver(
            () => this._updateBaseTransform());
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
        this.g.selectAll('g[data-srcline]')
            .style('cursor', 'pointer')
            .on('click', function(event) {
                event.stopPropagation();
                const el = d3.select(this);
                const line = parseInt(el.attr('data-srcline'), 10);
                const column = parseInt(el.attr('data-srccol'), 10);
                const file = el.attr('data-srcfile');
                if (!Number.isNaN(line)) {
                    viewEventBus.emit('editor:goto-source', { file, line, column });
                }
            });

        const pending = this._pendingHighlight;
        this._pendingHighlight = null;
        if (pending && this._selectionApplies(pending)) {
            this.setHighlight(pending);
        }
    }
    destroy() {
        viewEventBus.off('lvs:schem-select', this._onLvsSelect);
        viewEventBus.off('lvs:clear', this._onLvsClear);
        this.clearHighlight();
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
    }
}
