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

        this.series = [];
        this.currentTransform = d3.zoomIdentity;
        this._yZoomScale = 1;
        this._yPanOffset = 0;
        this._crosshairX = null;
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
            .scaleExtent([1, 100])
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

    _nearestIndex(xArr, xValue) {
        const bisect = d3.bisector(d => d).left;
        let idx = bisect(xArr, xValue);
        if (idx > 0 && idx < xArr.length) {
            if (Math.abs(xArr[idx - 1] - xValue) < Math.abs(xArr[idx] - xValue)) {
                idx = idx - 1;
            }
        }
        return Math.max(0, Math.min(xArr.length - 1, idx));
    }

    // Snaps an x value onto the sample grid of the first visible series
    // (the first series when all are hidden). When every series shares one
    // grid, the common case, this is the grid of all of them.
    _snapX(xValue) {
        const ref = this.series.find(s => s.visible) || this.series[0];
        if (!ref) return null;
        return ref.x[this._nearestIndex(ref.x, xValue)];
    }

    // Draws the crosshair at an already-snapped x value. Each series' dot
    // and tooltip row use that series' own nearest sample, so dots stay on
    // their curves even when series are sampled on different grids.
    _showCrosshairAt(xValue) {
        if (!this._xScale || !this._yScale) return;
        const visibleSeries = this.series.filter(s => s.visible);
        if (!visibleSeries.length) {
            this.crosshairG.style('display', 'none');
            this.tooltipEl.style.display = 'none';
            return;
        }

        this._crosshairX = xValue;
        const lineX = this._xScale(xValue);

        this.crosshairG.style('display', null);
        this.crosshairLine
            .attr('x1', lineX).attr('y1', 0)
            .attr('x2', lineX).attr('y2', this._plotH);

        const withIdx = visibleSeries.map(s => (
            { s, idx: this._nearestIndex(s.x, xValue) }));
        const dots = this.crosshairG.selectAll('circle.simplot-dot')
            .data(withIdx, d => d.s.name);

        dots.enter()
            .append('circle')
            .attr('class', 'simplot-dot')
            .attr('r', 3.5)
            .merge(dots)
            .attr('cx', d => {
                const x = d.s.x[d.idx];
                return isFinite(x) ? this._xScale(x) : -100;
            })
            .attr('cy', d => {
                const v = d.s.values[d.idx];
                return isFinite(v) ? this._yScale(v) : -100;
            })
            .attr('fill', d => d.s.color);

        dots.exit().remove();

        const fmtX = d3.format('.4~s');
        const fmtY = d3.format('.4~s');
        let html = `<span class="simplot-tooltip-x">${this.options.xlabel}: ${fmtX(xValue)}</span>`;
        withIdx.forEach(({ s, idx }) => {
            const v = s.values[idx];
            const vStr = isFinite(v) ? fmtY(v) : '—';
            html += `<span style="color:${s.color}">${s.name}: ${vStr}</span>`;
        });
        this.tooltipEl.innerHTML = html;
        this.tooltipEl.style.display = 'flex';
    }

    _onMouseMove(event) {
        if (!this._xScale || !this.series.length) return;

        const [mx] = d3.pointer(event, this.plotArea.node());
        const snapped = this._snapX(this._xScale.invert(mx));
        if (snapped === null) return;
        this._showCrosshairAt(snapped);
        this._emitCrosshairXChange(snapped);
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
            this.svg.call(this.zoom.transform, transform);
        } finally {
            this._suppressXDomainChange = false;
        }
    }

    setCrosshairX(xValue, { suppressEvent = false } = {}) {
        if (!this.series.length || !this._xScale) return;
        // Re-snap the incoming value: linked plots may be sampled on
        // different grids than the sender.
        const snapped = this._snapX(xValue);
        if (snapped === null) return;
        this._withCrosshairSuppression(suppressEvent, () => {
            this._showCrosshairAt(snapped);
            this._emitCrosshairXChange(snapped);
        });
    }

    clearCrosshair({ suppressEvent = false } = {}) {
        this._crosshairX = null;
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
        this.svg.call(this.zoom.transform, state.transform);
    }

    resetZoom() {
        this.currentTransform = d3.zoomIdentity;
        this._yZoomScale = 1;
        this._yPanOffset = 0;
        this.svg.call(this.zoom.transform, d3.zoomIdentity);
    }

    setData(series) {
        // Each series carries its own x array (ascending, enforced by the
        // backend); series of one plot may be sampled on different grids.
        // Non-finite values arrive as null (JSON has no NaN/Infinity, see
        // Plot2D.element_webdata); map them back to NaN so the isFinite gap
        // handling in the line/crosshair rendering applies.
        this.series = series.map((s, i) => ({
            ...s,
            x: s.x.map(v => v === null ? NaN : v),
            values: s.values.map(v => v === null ? NaN : v),
            color: s.color || signalColor(i),
            visible: true,
        }));
        this._updateLegend();
        // The old crosshair position belongs to the previous sweep: _render()
        // would restore it at a stale position. Cleared locally
        // (suppressEvent) so that replacing one plot's data does not drop the
        // crosshair on the linked plots of its group, which keep their data.
        this.clearCrosshair({ suppressEvent: true });
        this.currentTransform = d3.zoomIdentity;
        this._yZoomScale = 1;
        this._yPanOffset = 0;
        // Render once before calling zoom.transform so Chromium doesn't try
        // to resolve relative SVG lengths during default zoom extent lookup.
        this._render();
        if (this._plotW > 0 && this._plotH > 0) {
            this.svg.call(this.zoom.transform, d3.zoomIdentity);
        }
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

    _render() {
        if (!this.series.length) return;

        const dims = this._renderGeometry();
        if (!dims) return;
        const { w, h } = dims;

        const { xScale, xBase } = this._computeXScale(w);
        const yScale = this._computeYScale(xScale, h);

        this._renderAxesAndGrid(xScale, yScale, w, h);
        this._renderSeries(xScale, yScale);

        // Store scales/dimensions for crosshair interaction.
        this._xScale = xScale;
        this._yScale = yScale;
        this._xBase = xBase;
        this._plotW = w;
        this._plotH = h;

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
    // the un-zoomed scale, returned for crosshair math. The domain is the
    // union of all series' x extents (hidden series included, so toggling
    // visibility does not re-scale the x axis).
    _computeXScale(w) {
        let xMin = Infinity, xMax = -Infinity;
        this.series.forEach(s => {
            const [lo, hi] = d3.extent(s.x);
            if (lo !== undefined && lo < xMin) xMin = lo;
            if (hi !== undefined && hi > xMax) xMax = hi;
        });
        if (!isFinite(xMin)) { xMin = 0; xMax = 1; }
        const xDomain = [xMin, xMax];
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

    // Y scale fitted to the visible series within the current x range, with the
    // Y zoom/pan applied (in log space for a log axis).
    _computeYScale(xScale, h) {
        const [xLo, xHi] = xScale.domain();
        let yMin = Infinity, yMax = -Infinity;
        this.series.filter(s => s.visible).forEach(s => {
            for (let i = 0; i < s.values.length; i++) {
                const x = s.x[i];
                if (x >= xLo && x <= xHi) {
                    const v = s.values[i];
                    if (isFinite(v)) {
                        if (v < yMin) yMin = v;
                        if (v > yMax) yMax = v;
                    }
                }
            }
        });
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
        // One line generator per series, closing over that series' own x
        // array. A non-finite x or y is a gap, not a path corruption.
        const line = (s) => d3.line()
            .defined((d, i) => isFinite(d) && isFinite(s.x[i]))
            .x((d, i) => xScale(s.x[i]))
            .y(d => yScale(d));

        const visibleSeries = this.series.filter(s => s.visible);

        const paths = this.plotClip.selectAll('path.simplot-line')
            .data(visibleSeries, d => d.name);

        paths.enter()
            .append('path')
            .attr('class', 'simplot-line')
            .merge(paths)
            .attr('d', d => line(d)(d.values))
            .attr('stroke', d => d.color)
            .attr('fill', 'none')
            .attr('stroke-width', 1.5);

        paths.exit().remove();
    }

    // Sizes the hover rect to the plot area and re-draws the crosshair at
    // its stored x value, so it survives a re-render (resize, zoom,
    // recolor).
    _restoreCrosshair() {
        this.hoverRect.attr('width', this._plotW).attr('height', this._plotH);
        if (this._crosshairX !== null) {
            this._showCrosshairAt(this._crosshairX);
        }
    }

    destroy() {
        clearTimeout(this._resizeTimer);
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
