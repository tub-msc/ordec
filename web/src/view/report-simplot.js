// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import * as d3 from "d3";
import { isDark } from "../theme.js";

const MARGIN = { top: 10, right: 15, bottom: 35, left: 60 };

// Dark mode: oscilloscope-style bright signal colors on dark background
const SIGNAL_COLORS_DARK = [
    '#33ff33', // green (classic scope)
    '#ff3333', // red
    '#ffff33', // yellow
    '#33ffff', // cyan
    '#ff33ff', // magenta
    '#ff9933', // orange
    '#66bbff', // light blue
    '#ff6699', // pink
];

// Light mode: saturated colors readable on white background
const SIGNAL_COLORS_LIGHT = [
    '#1f77b4', // blue
    '#d62728', // red
    '#2ca02c', // green
    '#ff7f0e', // orange
    '#9467bd', // purple
    '#8c564b', // brown
    '#e377c2', // pink
    '#17becf', // cyan
];

function signalColor(i) {
    const palette = isDark() ? SIGNAL_COLORS_DARK : SIGNAL_COLORS_LIGHT;
    if (i < palette.length) return palette[i];
    const hue = (i * 137.508) % 360;
    const lightness = isDark() ? 60 : 40;
    return `hsl(${hue}, 80%, ${lightness}%)`;
}

// First sample index of every pixel column 0..w+1 of xScale, by bisection
// (x is sorted): sample i lies in column c for starts[c] <= i < starts[c + 1],
// c = -1 and c = w + 1 collect the samples left and right of the plot.
function columnStarts(xValues, xScale) {
    const w = Math.floor(xScale.range()[1]);
    const starts = new Int32Array(w + 2);
    for (let c = 0; c <= w + 1; c++) {
        starts[c] = d3.bisectLeft(xValues, xScale.invert(c));
    }
    return starts;
}

// Samples per block on the lowest pyramid level (see buildPyramid).
const PYRAMID_BLOCK = 16;

// Min/max pyramid of a series: level k holds, per block of
// PYRAMID_BLOCK * 2**k samples, the index of its minimum and maximum (first
// occurrence on ties), or -1 for blocks with a non-finite sample. A trailing
// partial block is left out. With it, rangeMinMax finds the extremes of a
// pixel column in O(PYRAMID_BLOCK + log n) instead of visiting all its
// samples. Memory: about 16 / PYRAMID_BLOCK bytes per sample.
function buildPyramid(values) {
    const B = PYRAMID_BLOCK;
    let min = new Int32Array(Math.floor(values.length / B));
    let max = new Int32Array(min.length);
    for (let j = 0; j < min.length; j++) {
        const m = [j * B, j * B];
        if (!scanMinMax(values, j * B, (j + 1) * B, m)) m[0] = m[1] = -1;
        min[j] = m[0];
        max[j] = m[1];
    }
    const levels = [{ min, max }];
    while (min.length >= 2) {
        const up = { min: new Int32Array(min.length >> 1), max: new Int32Array(min.length >> 1) };
        for (let j = 0; j < up.min.length; j++) {
            const a = min[2 * j], b = min[2 * j + 1];
            if (a < 0 || b < 0) {
                up.min[j] = up.max[j] = -1;
                continue;
            }
            // Ties go to the left child, which holds the lower index.
            up.min[j] = values[b] < values[a] ? b : a;
            const c = max[2 * j], d = max[2 * j + 1];
            up.max[j] = values[d] > values[c] ? d : c;
        }
        levels.push(up);
        ({ min, max } = up);
    }
    return levels;
}

// Updates m = [iMin, iMax] with the samples [from, to), visited in index
// order (first occurrence wins on ties). Returns false at the first
// non-finite sample.
function scanMinMax(values, from, to, m) {
    let iMin = m[0], iMax = m[1];
    for (let i = from; i < to; i++) {
        const v = values[i];
        if (!isFinite(v)) return false;
        if (v < values[iMin]) iMin = i;
        if (v > values[iMax]) iMax = i;
    }
    m[0] = iMin;
    m[1] = iMax;
    return true;
}

// [iMin, iMax] of the samples [s, e) (first occurrence on ties), or null if
// the range holds a non-finite sample. Scans the partial blocks at both ends
// and takes the whole blocks in between from the pyramid, by the usual
// bottom-up segment decomposition.
function rangeMinMax(values, pyramid, s, e) {
    const B = PYRAMID_BLOCK;
    const m = [s, s];
    let bs = Math.ceil(s / B), be = Math.floor(e / B);
    if (bs >= be) return scanMinMax(values, s, e, m) ? m : null;
    if (!scanMinMax(values, s, bs * B, m) || !scanMinMax(values, be * B, e, m)) return null;
    // Blocks are taken out of index order, so ties compare indices.
    const take = ({ min, max }, j) => {
        const jMin = min[j], jMax = max[j];
        if (jMin < 0) return false;
        const vMin = values[jMin], vMax = values[jMax];
        if (vMin < values[m[0]] || (vMin === values[m[0]] && jMin < m[0])) m[0] = jMin;
        if (vMax > values[m[1]] || (vMax === values[m[1]] && jMax < m[1])) m[1] = jMax;
        return true;
    };
    for (let k = 0; bs < be; k++) {
        if (bs & 1) {
            if (!take(pyramid[k], bs)) return null;
            bs++;
        }
        if (be & 1) {
            be--;
            if (!take(pyramid[k], be)) return null;
        }
        bs >>= 1;
        be >>= 1;
    }
    return m;
}

// Reduces the samples [i0, i1) of one series to the first, minimum, maximum
// and last sample per pixel column (see columnStarts and docs/dev/webui.rst).
// Non-finite samples become a single NaN, a gap for d3.line. Also returns the
// y extent of the finite samples inside the plot, for the y autoscale.
// Columns without non-finite samples get their extremes from the pyramid
// (see buildPyramid); the others are scanned and split into finite runs.
function reduceColumns(xValues, values, pyramid, starts, i0, i1) {
    const w = starts.length - 2;
    const xs = [], ys = [];
    let yMin = Infinity, yMax = -Infinity;
    let gap = true;  // last output point is a gap (or no output yet)
    const push = (i) => {
        xs.push(xValues[i]);
        ys.push(values[i]);
    };
    // Emits a finite run [iFirst, iLast] with its extremes, in index order.
    const emit = (iFirst, iMin, iMax, iLast) => {
        const a = Math.min(iMin, iMax), b = Math.max(iMin, iMax);
        push(iFirst);
        if (a > iFirst) push(a);
        if (b > a) push(b);
        if (iLast > b) push(iLast);
        gap = false;
    };
    // Column c holds the samples [starts[c], starts[c + 1]); c = -1 and
    // c = w + 1 hold the samples left and right of the plot.
    for (let c = -1; c <= w + 1; c++) {
        const s = c < 0 ? i0 : Math.max(starts[c], i0);
        const e = c > w ? i1 : Math.min(starts[c + 1], i1);
        if (s >= e) continue;
        const inPlot = c >= 0 && c <= w;
        const m = rangeMinMax(values, pyramid, s, e);
        if (m) {
            emit(s, m[0], m[1], e - 1);
            if (inPlot) {
                yMin = Math.min(yMin, values[m[0]]);
                yMax = Math.max(yMax, values[m[1]]);
            }
            continue;
        }
        let iFirst = -1, iMin = 0, iMax = 0, iLast = 0;  // iFirst < 0: no run
        for (let i = s; i < e; i++) {
            const v = values[i];
            if (!isFinite(v)) {
                if (iFirst >= 0) emit(iFirst, iMin, iMax, iLast);
                iFirst = -1;
                if (!gap) {
                    xs.push(NaN);
                    ys.push(NaN);
                    gap = true;
                }
                continue;
            }
            if (inPlot) {
                if (v < yMin) yMin = v;
                if (v > yMax) yMax = v;
            }
            if (iFirst < 0) {
                iFirst = iMin = iMax = iLast = i;
                continue;
            }
            iLast = i;
            if (v < values[iMin]) iMin = i;
            if (v > values[iMax]) iMax = i;
        }
        if (iFirst >= 0) emit(iFirst, iMin, iMax, iLast);
    }
    return { x: xs, y: ys, yMin, yMax };
}

export class SimPlot {
    constructor(container, options = {}) {
        this.options = {
            xlabel: options.xlabel || '',
            ylabel: options.ylabel || '',
            xscale: options.xscale || 'linear',
            yscale: options.yscale || 'linear',
            fixedHeight: options.fixedHeight || null,
        };

        // Group-sync callbacks, set only by setSyncCallbacks() (see the plot
        // group wiring in report.js).
        this.onXDomainChange = null;
        this.onCrosshairXChange = null;

        this.xValues = null;
        this._maxZoom = 100;
        this.series = [];
        this.currentTransform = d3.zoomIdentity;
        this._yZoomScale = 1;
        this._yPanOffset = 0;
        this._crosshairIndex = null;
        this._suppressXDomainChange = false;
        this._suppressCrosshairChange = false;

        // DOM structure: wrapper > [legend, svg]
        this.wrapper = document.createElement('div');
        this.wrapper.classList.add('simplot');
        if (this.options.fixedHeight !== null) {
            this.wrapper.style.width = '100%';
            this.wrapper.style.flex = '0 0 auto';
            this.wrapper.style.height = SimPlot._normalizeCssSize(this.options.fixedHeight);
        }
        container.appendChild(this.wrapper);

        this.legendEl = document.createElement('div');
        this.legendEl.classList.add('simplot-legend');
        this.wrapper.appendChild(this.legendEl);

        this.svg = d3.select(this.wrapper).append('svg');

        this.defaultZoomBtn = document.createElement('button');
        this.defaultZoomBtn.type = 'button';
        this.defaultZoomBtn.classList.add('simplot-default-zoom');
        this.defaultZoomBtn.innerText = 'Default zoom';
        this.defaultZoomBtn.addEventListener('click', () => this.resetZoom());

        // Crosshair tooltip
        this.tooltipEl = document.createElement('div');
        this.tooltipEl.classList.add('simplot-tooltip');
        this.wrapper.appendChild(this.tooltipEl);

        this._setupSvg();

        this._resizeTimer = null;
        this.resizeObserver = new ResizeObserver(() => {
            clearTimeout(this._resizeTimer);
            this._resizeTimer = setTimeout(() => this._render(), 30);
        });
        this.resizeObserver.observe(this.wrapper);

        // Re-color when theme changes
        this._themeObserver = new MutationObserver(() => {
            this._recolor();
        });
        this._themeObserver.observe(document.body, {
            attributes: true,
            attributeFilter: ['class'],
        });
    }

    _recolor() {
        this.series.forEach((s, i) => {
            s.color = signalColor(i);
        });
        this.crosshairLine.attr('stroke', isDark() ? '#888' : '#999');
        this._updateLegend();
        this._render();
    }

    _setupSvg() {
        this.clipId = 'clip-' + Math.random().toString(36).slice(2, 11);
        this.svg.append('defs').append('clipPath')
            .attr('id', this.clipId)
            .append('rect');

        this.plotArea = this.svg.append('g');

        // Grid lines (behind everything)
        this.xGridG = this.plotArea.append('g').attr('class', 'simplot-grid');
        this.yGridG = this.plotArea.append('g').attr('class', 'simplot-grid');

        this.plotClip = this.plotArea.append('g')
            .attr('clip-path', `url(#${this.clipId})`);

        this.xAxisG = this.plotArea.append('g').attr('class', 'simplot-axis');
        this.yAxisG = this.plotArea.append('g').attr('class', 'simplot-axis');

        this.xLabelEl = this.plotArea.append('text')
            .attr('class', 'simplot-axis-label')
            .attr('text-anchor', 'middle')
            .text(this.options.xlabel);

        this.yLabelEl = this.plotArea.append('text')
            .attr('class', 'simplot-axis-label')
            .attr('text-anchor', 'middle')
            .attr('transform', 'rotate(-90)')
            .text(this.options.ylabel);

        // Crosshair overlay (on top of everything, inside clip)
        this.crosshairG = this.plotArea.append('g')
            .attr('class', 'simplot-crosshair')
            .attr('clip-path', `url(#${this.clipId})`)
            .style('display', 'none');

        this.crosshairLine = this.crosshairG.append('line')
            .attr('stroke', isDark() ? '#888' : '#999')
            .attr('stroke-width', 1)
            .attr('stroke-dasharray', '4,3');

        // Hover rect to capture mouse events over the plot area
        this.hoverRect = this.plotArea.append('rect')
            .attr('class', 'simplot-hover-rect')
            .attr('fill', 'none')
            .attr('pointer-events', 'all');

        this.hoverRect
            .on('mousemove', (event) => this._onMouseMove(event))
            .on('mouseleave', () => this._onMouseLeave());

        this.zoom = d3.zoom()
            .scaleExtent([1, this._maxZoom])
            .filter(event => {
                // Let shift events through to Y axis handlers instead
                if (event.shiftKey) return false;
                // Block double-click from D3 zoom (we handle it ourselves)
                if (event.type === 'dblclick') return false;
                return true;
            })
            .on('zoom', (event) => {
                this.currentTransform = event.transform;
                this._render();
                this._emitXDomainChange();
            });
        this.svg.call(this.zoom);

        // Shift+scroll → Y axis zoom
        this.svg.node().addEventListener('wheel', (event) => {
            if (!event.shiftKey) return;
            event.preventDefault();
            const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
            this._yZoomScale = Math.max(0.01, Math.min(1000, this._yZoomScale * factor));

            // Zoom around the mouse Y position
            if (this._yScale) {
                const [, my] = d3.pointer(event, this.plotArea.node());
                const yAtMouse = this._yScale.invert(my);
                // Adjust pan so the value under the cursor stays put
                this._yPanOffset = yAtMouse - (yAtMouse - this._yPanOffset) / factor;
            }
            this._render();
        }, { passive: false });

        // Shift+drag → Y axis pan
        this._yDrag = null;
        this.svg.node().addEventListener('mousedown', (event) => {
            if (!event.shiftKey || event.button !== 0) return;
            event.preventDefault();
            this._yDrag = { startY: event.clientY, startOffset: this._yPanOffset };
        });
        window.addEventListener('mousemove', this._yDragMove = (event) => {
            if (!this._yDrag || !this._yScale) return;
            const dy = event.clientY - this._yDrag.startY;
            // Convert pixel delta to data units
            const domain = this._yScale.domain();
            const range = this._yScale.range();
            const dataPerPx = (domain[0] - domain[1]) / (range[0] - range[1]);
            this._yPanOffset = this._yDrag.startOffset + dy * dataPerPx;
            this._render();
        });
        window.addEventListener('mouseup', this._yDragEnd = () => {
            this._yDrag = null;
        });

        // Double-click → reset both axes
        this.svg.on('dblclick', () => this.resetZoom());

        // Current scales (updated in _render, used by crosshair)
        this._xScale = null;
        this._yScale = null;
        this._xBase = null;
        this._plotW = 0;
        this._plotH = 0;
        // y extent of the last reduction (empty: _computeYScale falls back
        // to [-1, 1]) and the pending _draw frame.
        this._yExtent = [Infinity, -Infinity];
        this._drawFrame = null;
    }

    static _normalizeCssSize(size) {
        if (typeof size === 'number') {
            return `${size}px`;
        }
        return size;
    }

    setSyncCallbacks({ onXDomainChange = null, onCrosshairXChange = null } = {}) {
        this.onXDomainChange = onXDomainChange;
        this.onCrosshairXChange = onCrosshairXChange;
    }

    getXDomain() {
        if (!this._xScale) return null;
        return this._xScale.domain().slice();
    }

    _emitXDomainChange() {
        if (this._suppressXDomainChange || !this.onXDomainChange || !this._xScale) {
            return;
        }
        this.onXDomainChange(this._xScale.domain().slice());
    }

    _emitCrosshairXChange(xValue) {
        if (this._suppressCrosshairChange || !this.onCrosshairXChange) {
            return;
        }
        this.onCrosshairXChange(xValue);
    }

    _nearestXIndex(xValue) {
        let idx = d3.bisectLeft(this.xValues, xValue);
        if (idx > 0 && idx < this.xValues.length) {
            if (Math.abs(this.xValues[idx - 1] - xValue) < Math.abs(this.xValues[idx] - xValue)) {
                idx = idx - 1;
            }
        }
        return Math.max(0, Math.min(this.xValues.length - 1, idx));
    }

    _showCrosshairAtIndex(idx) {
        if (!this._xScale || !this._yScale || !this.xValues) return;
        const visibleSeries = this.series.filter(s => s.visible);
        if (!visibleSeries.length) {
            this.crosshairG.style('display', 'none');
            this.tooltipEl.style.display = 'none';
            return;
        }

        this._crosshairIndex = idx;
        const snappedX = this._xScale(this.xValues[idx]);

        this.crosshairG.style('display', null);
        this.crosshairLine
            .attr('x1', snappedX).attr('y1', 0)
            .attr('x2', snappedX).attr('y2', this._plotH);

        const dots = this.crosshairG.selectAll('circle.simplot-dot')
            .data(visibleSeries, d => d.name);

        dots.enter()
            .append('circle')
            .attr('class', 'simplot-dot')
            .attr('r', 3.5)
            .merge(dots)
            .attr('cx', snappedX)
            .attr('cy', d => {
                const v = d.values[idx];
                return isFinite(v) ? this._yScale(v) : -100;
            })
            .attr('fill', d => d.color);

        dots.exit().remove();

        const fmtX = d3.format('.4~s');
        const fmtY = d3.format('.4~s');
        let html = `<span class="simplot-tooltip-x">${this.options.xlabel}: ${fmtX(this.xValues[idx])}</span>`;
        visibleSeries.forEach(s => {
            const v = s.values[idx];
            const vStr = isFinite(v) ? fmtY(v) : '—';
            html += `<span style="color:${s.color}">${s.name}: ${vStr}</span>`;
        });
        this.tooltipEl.innerHTML = html;
        this.tooltipEl.style.display = 'flex';
    }

    _onMouseMove(event) {
        if (!this._xScale || !this.xValues) return;

        const [mx] = d3.pointer(event, this.plotArea.node());
        const xVal = this._xScale.invert(mx);
        const idx = this._nearestXIndex(xVal);
        this._showCrosshairAtIndex(idx);
        this._emitCrosshairXChange(this.xValues[idx]);
    }

    _onMouseLeave() {
        this.clearCrosshair();
    }

    _withCrosshairSuppression(suppressEvent, fn) {
        this._suppressCrosshairChange = suppressEvent;
        try {
            fn();
        } finally {
            this._suppressCrosshairChange = false;
        }
    }

    setXDomain(domain, { suppressEvent = false } = {}) {
        if (!this._xBase || !this._plotW || !domain || domain.length !== 2) return;
        let [x0, x1] = domain.map(Number);
        if (!isFinite(x0) || !isFinite(x1)) return;
        if (x1 < x0) {
            [x0, x1] = [x1, x0];
        }
        if (this.options.xscale === 'log') {
            x0 = Math.max(x0, 1e-30);
            x1 = Math.max(x1, x0 * 1.000001);
        } else if (Math.abs(x1 - x0) < 1e-30) {
            return;
        }

        const r0 = this._xBase(x0);
        const r1 = this._xBase(x1);
        if (!isFinite(r0) || !isFinite(r1) || Math.abs(r1 - r0) < 1e-12) return;

        const k = this._plotW / (r1 - r0);
        const tx = -k * r0;
        const transform = d3.zoomIdentity.translate(tx, 0).scale(k);

        this.currentTransform = transform;
        this._suppressXDomainChange = suppressEvent;
        try {
            this._applyTransform(transform);
        } finally {
            this._suppressXDomainChange = false;
        }
    }

    setCrosshairX(xValue, { suppressEvent = false } = {}) {
        if (!this.xValues || !this._xScale) return;
        const idx = this._nearestXIndex(xValue);
        this._withCrosshairSuppression(suppressEvent, () => {
            this._showCrosshairAtIndex(idx);
            this._emitCrosshairXChange(this.xValues[idx]);
        });
    }

    clearCrosshair({ suppressEvent = false } = {}) {
        this._crosshairIndex = null;
        this.crosshairG.style('display', 'none');
        this.tooltipEl.style.display = 'none';
        this._withCrosshairSuppression(suppressEvent, () => {
            this._emitCrosshairXChange(null);
        });
    }

    getZoomState() {
        return {
            transform: this.currentTransform,
            yZoomScale: this._yZoomScale,
            yPanOffset: this._yPanOffset,
        };
    }

    setZoomState(state) {
        this._yZoomScale = state.yZoomScale;
        this._yPanOffset = state.yPanOffset;
        this.currentTransform = state.transform;
        this._applyTransform(state.transform);
    }

    resetZoom() {
        this.currentTransform = d3.zoomIdentity;
        this._yZoomScale = 1;
        this._yPanOffset = 0;
        this._applyTransform(d3.zoomIdentity);
    }

    setData(xValues, series) {
        // Float64Arrays (see Plot2D.element_webdata), NaN marks gaps.
        this.xValues = xValues;
        this.series = series.map((s, i) => ({
            ...s,
            color: s.color || signalColor(i),
            visible: true,
            pyramid: buildPyramid(s.values),
        }));
        // x is sorted and finite (Plot2D.x is validated on the server).
        this._xExtent = [this.xValues[0], this.xValues[this.xValues.length - 1]];
        // Zoom limit: about ten samples across the plot width, at least 100x.
        this._maxZoom = Math.max(100, this.xValues.length / 10);
        this.zoom.scaleExtent([1, this._maxZoom]);
        this._updateLegend();
        // The old crosshair index points into the previous sweep: _render()
        // would restore it at a stale position, or at NaN if the new data is
        // shorter. Cleared locally (suppressEvent) so that replacing one
        // plot's data does not drop the crosshair on the linked plots of its
        // group, which keep their data.
        this.clearCrosshair({ suppressEvent: true });
        this.currentTransform = d3.zoomIdentity;
        this._yZoomScale = 1;
        this._yPanOffset = 0;
        // Render once before calling zoom.transform so Chromium doesn't try
        // to resolve relative SVG lengths during default zoom extent lookup.
        this._render();
        if (this._plotW > 0 && this._plotH > 0) {
            this._applyTransform(d3.zoomIdentity);
        }
    }

    // Applies a transform not coming from a zoom gesture. Its scale may exceed
    // _maxZoom (x-synchronized plots with other limits, a zoom state restored
    // after a re-run with fewer samples), so the limit is raised to it, else
    // d3-zoom snaps the next gesture back. setData resets the limit.
    _applyTransform(transform) {
        this.zoom.scaleExtent([1, Math.max(this._maxZoom, transform.k)]);
        this.svg.call(this.zoom.transform, transform);
    }

    getHiddenNames() {
        return new Set(this.series.filter(s => !s.visible).map(s => s.name));
    }

    setHiddenNames(names) {
        let changed = false;
        this.series.forEach(s => {
            const hide = names.has(s.name);
            if (s.visible === hide) {
                s.visible = !hide;
                changed = true;
            }
        });
        if (changed) {
            this._updateLegend();
            this._render();
        }
    }

    _updateLegend() {
        this.legendEl.innerHTML = '';
        this.legendEl.appendChild(this.defaultZoomBtn);
        this.series.forEach(s => {
            const item = document.createElement('span');
            item.classList.add('simplot-legend-item');
            if (!s.visible) item.classList.add('simplot-legend-hidden');
            const swatch = document.createElement('span');
            swatch.classList.add('simplot-legend-swatch');
            swatch.style.backgroundColor = s.color;
            item.appendChild(swatch);
            item.appendChild(document.createTextNode(s.name));
            item.addEventListener('click', () => {
                s.visible = !s.visible;
                item.classList.toggle('simplot-legend-hidden', !s.visible);
                this._render();
            });
            this.legendEl.appendChild(item);
        });
    }

    // Updates geometry and scales synchronously and schedules the drawing for
    // the next animation frame. Browsers may dispatch several wheel/mousemove
    // events per frame (the spec leaves coalescing to them); this way they
    // cost one reduction. Callers rely on the scales being current right
    // after this returns (x-domain group sync, setXDomain, crosshair, Y zoom
    // anchor). After a change of the x domain or of the visible series, the
    // y extent is only known after the reduction, so until the frame
    // _yScale uses the previous extent.
    _render() {
        if (!this.xValues || !this.series.length) return;

        const dims = this._renderGeometry();
        if (!dims) return;
        const { w, h } = dims;

        const { xScale, xBase } = this._computeXScale(w);
        this._xScale = xScale;
        this._xBase = xBase;
        this._yScale = this._computeYScale(...this._yExtent, h);
        this._plotW = w;
        this._plotH = h;

        if (this._drawFrame === null) {
            this._drawFrame = requestAnimationFrame(() => {
                this._drawFrame = null;
                this._draw();
            });
        }
    }

    _draw() {
        this._yExtent = this._reduceSeries(this._xScale);
        this._yScale = this._computeYScale(...this._yExtent, this._plotH);
        this._renderAxesAndGrid(this._xScale, this._yScale, this._plotW, this._plotH);
        this._renderSeries(this._xScale, this._yScale);
        this._restoreCrosshair();
    }

    // Sizes the SVG, plot area and clip rect from the current wrapper size.
    // Returns the inner plot dimensions {w, h}, or null when there is no room
    // to draw (during teardown or before the first layout).
    _renderGeometry() {
        const wrapperRect = this.wrapper.getBoundingClientRect();
        const legendH = this.legendEl.getBoundingClientRect().height;
        const svgW = wrapperRect.width;
        const svgH = wrapperRect.height - legendH;
        const w = svgW - MARGIN.left - MARGIN.right;
        const h = svgH - MARGIN.top - MARGIN.bottom;

        if (w <= 0 || h <= 0) return null;

        this.svg.attr('width', svgW).attr('height', svgH);
        this.plotArea.attr('transform', `translate(${MARGIN.left},${MARGIN.top})`);
        this.svg.select(`#${this.clipId} rect`).attr('width', w).attr('height', h);
        return { w, h };
    }

    // X scale for the data extent under the current zoom transform. xBase is
    // the un-zoomed scale, returned for crosshair math.
    _computeXScale(w) {
        const xDomain = this._xExtent;
        let xBase;
        if (this.options.xscale === 'log') {
            xBase = d3.scaleLog()
                .domain([Math.max(xDomain[0], 1e-30), xDomain[1]])
                .range([0, w]);
        } else {
            xBase = d3.scaleLinear().domain(xDomain).range([0, w]);
        }
        return { xScale: this.currentTransform.rescaleX(xBase), xBase };
    }

    // Reduces every visible series into s.reduced (see reduceColumns) and
    // returns their y extent. Reductions are kept while the x domain and plot
    // width are unchanged, so y-only renders (Y zoom/pan, legend) reuse them.
    _reduceSeries(xScale) {
        const key = [...xScale.domain(), ...xScale.range()].join();
        if (key !== this._reducedKey) {
            this._reducedKey = key;
            this.series.forEach(s => { s.reduced = null; });
        }
        let starts = null, i0, i1;
        let yMin = Infinity, yMax = -Infinity;
        for (const s of this.series) {
            if (!s.visible) continue;
            if (!s.reduced) {
                if (!starts) {
                    starts = columnStarts(this.xValues, xScale);
                    i0 = Math.max(0, starts[0] - 1);
                    i1 = Math.min(this.xValues.length, starts[starts.length - 1] + 1);
                }
                s.reduced = reduceColumns(this.xValues, s.values, s.pyramid, starts, i0, i1);
            }
            yMin = Math.min(yMin, s.reduced.yMin);
            yMax = Math.max(yMax, s.reduced.yMax);
        }
        return [yMin, yMax];
    }

    // Y scale fitted to the given y extent of the visible samples, with the
    // Y zoom/pan applied (in log space for a log axis).
    _computeYScale(yMin, yMax, h) {
        if (!isFinite(yMin)) { yMin = -1; yMax = 1; }

        if (this.options.yscale === 'log') {
            const logMin = Math.log10(Math.max(yMin, 1e-30));
            const logMax = Math.log10(Math.max(yMax, 1e-29));
            const logPad = (logMax - logMin) * 0.05 || 0.5;
            const logCenter = (logMin + logMax) / 2 + this._yPanOffset;
            const logHalfRange = ((logMax - logMin) / 2 + logPad) / this._yZoomScale;
            return d3.scaleLog()
                .domain([10 ** (logCenter - logHalfRange), 10 ** (logCenter + logHalfRange)])
                .range([h, 0]);
        }
        const yPad = (yMax - yMin) * 0.05 || 0.5;
        const yCenter = (yMin + yMax) / 2 + this._yPanOffset;
        const yHalfRange = ((yMax - yMin) / 2 + yPad) / this._yZoomScale;
        return d3.scaleLinear()
            .domain([yCenter - yHalfRange, yCenter + yHalfRange])
            .range([h, 0]);
    }

    _renderAxesAndGrid(xScale, yScale, w, h) {
        const xTickCount = Math.max(Math.floor(w / 80), 3);
        const yTickCount = Math.max(Math.floor(h / 40), 3);

        const xAxis = d3.axisBottom(xScale);
        if (this.options.xscale === 'log') {
            xAxis.ticks(xTickCount, "~s");
        } else {
            xAxis.ticks(xTickCount).tickFormat(d3.format("~s"));
        }
        this.xAxisG
            .attr('transform', `translate(0,${h})`)
            .call(xAxis);

        const yAxis = d3.axisLeft(yScale);
        if (this.options.yscale === 'log') {
            yAxis.ticks(yTickCount, "~s");
        } else {
            yAxis.ticks(yTickCount).tickFormat(d3.format("~s"));
        }
        this.yAxisG.call(yAxis);

        const xGrid = d3.axisBottom(xScale).tickSize(-h).tickFormat('');
        if (this.options.xscale === 'log') {
            xGrid.ticks(xTickCount, "");
        } else {
            xGrid.ticks(xTickCount);
        }
        this.xGridG
            .attr('transform', `translate(0,${h})`)
            .call(xGrid);

        const yGrid = d3.axisLeft(yScale).tickSize(-w).tickFormat('');
        if (this.options.yscale === 'log') {
            yGrid.ticks(yTickCount, "");
        } else {
            yGrid.ticks(yTickCount);
        }
        this.yGridG.call(yGrid);

        this.xLabelEl.attr('x', w / 2).attr('y', h + MARGIN.bottom - 5);
        this.yLabelEl.attr('x', -h / 2).attr('y', -MARGIN.left + 15);
    }

    _renderSeries(xScale, yScale) {
        const path = (r) => d3.line()
            .defined(v => isFinite(v))
            .x((v, i) => xScale(r.x[i]))
            .y(v => yScale(v))(r.y);

        const visibleSeries = this.series.filter(s => s.visible);

        const paths = this.plotClip.selectAll('path.simplot-line')
            .data(visibleSeries, d => d.name);

        paths.enter()
            .append('path')
            .attr('class', 'simplot-line')
            .merge(paths)
            .attr('d', d => path(d.reduced))
            .attr('stroke', d => d.color)
            .attr('fill', 'none')
            .attr('stroke-width', 1.5);

        paths.exit().remove();
    }

    // Sizes the hover rect to the plot area and re-draws the crosshair at its
    // stored index, so it survives a re-render (resize, zoom, recolor).
    _restoreCrosshair() {
        this.hoverRect.attr('width', this._plotW).attr('height', this._plotH);
        if (this._crosshairIndex !== null) {
            this._showCrosshairAtIndex(this._crosshairIndex);
        }
    }

    destroy() {
        clearTimeout(this._resizeTimer);
        cancelAnimationFrame(this._drawFrame);
        this._drawFrame = null;
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
        if (this._themeObserver) {
            this._themeObserver.disconnect();
            this._themeObserver = null;
        }
        window.removeEventListener('mousemove', this._yDragMove);
        window.removeEventListener('mouseup', this._yDragEnd);
    }
}
