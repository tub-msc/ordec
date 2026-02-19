// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import * as d3 from "d3";

const MARGIN = { top: 10, right: 15, bottom: 35, left: 60 };

// Oscilloscope-style signal colors: bright on dark background
const SIGNAL_COLORS = [
    '#33ff33', // green (classic scope)
    '#ff3333', // red
    '#ffff33', // yellow
    '#33ffff', // cyan
    '#ff33ff', // magenta
    '#ff9933', // orange
    '#66bbff', // light blue
    '#ff6699', // pink
];

function signalColor(i) {
    if (i < SIGNAL_COLORS.length) return SIGNAL_COLORS[i];
    // Distinct colors beyond the common signal colors (golden angle)
    const hue = (i * 137.508) % 360;
    return `hsl(${hue}, 100%, 60%)`;
}

export class SimPlot {
    constructor(container, options = {}) {
        this.options = {
            xlabel: options.xlabel || '',
            ylabel: options.ylabel || '',
            xscale: options.xscale || 'linear',
            yscale: options.yscale || 'linear',
        };

        this.xValues = null;
        this.series = [];
        this.currentTransform = d3.zoomIdentity;
        this._yZoomScale = 1;
        this._yPanOffset = 0;

        // DOM structure: wrapper > [legend, svg]
        this.wrapper = document.createElement('div');
        this.wrapper.classList.add('simplot');
        container.appendChild(this.wrapper);

        this.legendEl = document.createElement('div');
        this.legendEl.classList.add('simplot-legend');
        this.wrapper.appendChild(this.legendEl);

        this.svg = d3.select(this.wrapper).append('svg');

        // Crosshair tooltip
        this.tooltipEl = document.createElement('div');
        this.tooltipEl.classList.add('simplot-tooltip');
        this.wrapper.appendChild(this.tooltipEl);

        this._setupSvg();

        let resizeTimer;
        this.resizeObserver = new ResizeObserver(() => {
            clearTimeout(resizeTimer);
            // Wait before resizing to improve computational load
            resizeTimer = setTimeout(() => this._render(), 30);
        });
        this.resizeObserver.observe(this.wrapper);
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
            .attr('stroke', '#888')
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
        this.svg.on('dblclick', () => {
            this.currentTransform = d3.zoomIdentity;
            this.svg.call(this.zoom.transform, d3.zoomIdentity);
            this._yZoomScale = 1;
            this._yPanOffset = 0;
            this._render();
        });

        // Current scales (updated in _render, used by crosshair)
        this._xScale = null;
        this._yScale = null;
        this._plotH = 0;
    }

    _onMouseMove(event) {
        if (!this._xScale || !this.xValues) return;
        const visibleSeries = this.series.filter(s => s.visible);
        if (!visibleSeries.length) return;

        const [mx] = d3.pointer(event, this.plotArea.node());
        const xVal = this._xScale.invert(mx);

        // Binary search for nearest data index
        const bisect = d3.bisector(d => d).left;
        let idx = bisect(this.xValues, xVal);
        if (idx > 0 && idx < this.xValues.length) {
            // Pick the closer neighbor
            if (Math.abs(this.xValues[idx - 1] - xVal) < Math.abs(this.xValues[idx] - xVal)) {
                idx = idx - 1;
            }
        }
        idx = Math.max(0, Math.min(this.xValues.length - 1, idx));

        const snappedX = this._xScale(this.xValues[idx]);

        // Position crosshair line
        this.crosshairG.style('display', null);
        this.crosshairLine
            .attr('x1', snappedX).attr('y1', 0)
            .attr('x2', snappedX).attr('y2', this._plotH);

        // Update dot markers for visible series
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

        // Build tooltip text
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

    _onMouseLeave() {
        this.crosshairG.style('display', 'none');
        this.tooltipEl.style.display = 'none';
    }

    setData(xValues, series) {
        this.xValues = xValues;
        this.series = series.map((s, i) => ({
            ...s,
            color: s.color || signalColor(i),
            visible: true,
        }));
        this._updateLegend();
        this.currentTransform = d3.zoomIdentity;
        this._yZoomScale = 1;
        this._yPanOffset = 0;
        this.svg.call(this.zoom.transform, d3.zoomIdentity);
        this._render();
    }

    _updateLegend() {
        this.legendEl.innerHTML = '';
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
        if (!this.xValues || !this.series.length) return;

        const wrapperRect = this.wrapper.getBoundingClientRect();
        const legendH = this.legendEl.getBoundingClientRect().height;
        const svgW = wrapperRect.width;
        const svgH = wrapperRect.height - legendH;
        const w = svgW - MARGIN.left - MARGIN.right;
        const h = svgH - MARGIN.top - MARGIN.bottom;

        if (w <= 0 || h <= 0) return;

        this.svg.attr('width', svgW).attr('height', svgH);
        this.plotArea.attr('transform', `translate(${MARGIN.left},${MARGIN.top})`);
        this.svg.select(`#${this.clipId} rect`).attr('width', w).attr('height', h);

        // X scale
        const xDomain = d3.extent(this.xValues);
        let xBase;
        if (this.options.xscale === 'log') {
            xBase = d3.scaleLog()
                .domain([Math.max(xDomain[0], 1e-30), xDomain[1]])
                .range([0, w]);
        } else {
            xBase = d3.scaleLinear().domain(xDomain).range([0, w]);
        }
        const xScale = this.currentTransform.rescaleX(xBase);

        // Y extent from visible x range for visible series
        const [xLo, xHi] = xScale.domain();
        let yMin = Infinity, yMax = -Infinity;
        this.series.filter(s => s.visible).forEach(s => {
            for (let i = 0; i < s.values.length; i++) {
                const x = this.xValues[i];
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

        // Apply Y zoom/pan, working in log space for log scale
        let yScale;
        if (this.options.yscale === 'log') {
            const logMin = Math.log10(Math.max(yMin, 1e-30));
            const logMax = Math.log10(Math.max(yMax, 1e-29));
            const logPad = (logMax - logMin) * 0.05 || 0.5;
            const logCenter = (logMin + logMax) / 2 + this._yPanOffset;
            const logHalfRange = ((logMax - logMin) / 2 + logPad) / this._yZoomScale;
            yScale = d3.scaleLog()
                .domain([10 ** (logCenter - logHalfRange), 10 ** (logCenter + logHalfRange)])
                .range([h, 0]);
        } else {
            const yPad = (yMax - yMin) * 0.05 || 0.5;
            const yCenter = (yMin + yMax) / 2 + this._yPanOffset;
            const yHalfRange = ((yMax - yMin) / 2 + yPad) / this._yZoomScale;
            yScale = d3.scaleLinear()
                .domain([yCenter - yHalfRange, yCenter + yHalfRange])
                .range([h, 0]);
        }

        // Axes
        const xTickCount = Math.max(Math.floor(w / 80), 3);
        const yTickCount = Math.max(Math.floor(h / 40), 3);

        this.xAxisG
            .attr('transform', `translate(0,${h})`)
            .call(d3.axisBottom(xScale).ticks(xTickCount).tickFormat(d3.format("~s")));

        this.yAxisG
            .call(d3.axisLeft(yScale).ticks(yTickCount).tickFormat(d3.format("~s")));

        // Grid lines
        this.xGridG
            .attr('transform', `translate(0,${h})`)
            .call(d3.axisBottom(xScale).ticks(xTickCount).tickSize(-h).tickFormat(''));

        this.yGridG
            .call(d3.axisLeft(yScale).ticks(yTickCount).tickSize(-w).tickFormat(''));

        // Labels
        this.xLabelEl.attr('x', w / 2).attr('y', h + MARGIN.bottom - 5);
        this.yLabelEl.attr('x', -h / 2).attr('y', -MARGIN.left + 15);

        // Lines
        const line = d3.line()
            .defined((d) => isFinite(d))
            .x((d, i) => xScale(this.xValues[i]))
            .y(d => yScale(d));

        const visibleSeries = this.series.filter(s => s.visible);

        const paths = this.plotClip.selectAll('path.simplot-line')
            .data(visibleSeries, d => d.name);

        paths.enter()
            .append('path')
            .attr('class', 'simplot-line')
            .merge(paths)
            .attr('d', d => line(d.values))
            .attr('stroke', d => d.color)
            .attr('fill', 'none')
            .attr('stroke-width', 1.5);

        paths.exit().remove();

        // Store scales for crosshair interaction
        this._xScale = xScale;
        this._yScale = yScale;
        this._plotH = h;

        // Size the hover rect to cover plot area
        this.hoverRect.attr('width', w).attr('height', h);
    }

    destroy() {
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
        window.removeEventListener('mousemove', this._yDragMove);
        window.removeEventListener('mouseup', this._yDragEnd);
    }
}
