// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { Markdown, Html, PreformattedText, Svg, PassFail,
    Plot2d } from './report-elements.js';

class ReportPlotGroups {
    constructor() {
        this.groups = new Map();
        this.groupNameOfPlot = new Map();
    }

    _applyCrosshair(plot, crosshairX) {
        if (crosshairX === null) {
            plot.clearCrosshair({ suppressEvent: true });
        } else {
            plot.setCrosshairX(crosshairX, { suppressEvent: true });
        }
    }

    register(plot, groupName) {
        if (!groupName) return;
        let group = this.groups.get(groupName);
        if (!group) {
            group = {
                plots: new Set(),
                xDomain: null,
                crosshairX: undefined,
            };
            this.groups.set(groupName, group);
        }

        group.plots.add(plot);
        this.groupNameOfPlot.set(plot, groupName);
        plot.setSyncCallbacks({
            onXDomainChange: (xDomain) => this._onXDomainChange(groupName, plot, xDomain),
            onCrosshairXChange: (crosshairX) => this._onCrosshairXChange(groupName, plot, crosshairX),
        });
        if (!group.xDomain) {
            group.xDomain = plot.getXDomain();
        }

        if (group.xDomain) {
            plot.setXDomain(group.xDomain, { suppressEvent: true });
        }
        if (group.crosshairX !== undefined) {
            this._applyCrosshair(plot, group.crosshairX);
        }
    }

    unregister(plot) {
        const groupName = this.groupNameOfPlot.get(plot);
        if (!groupName) return;
        this.groupNameOfPlot.delete(plot);

        const group = this.groups.get(groupName);
        if (!group) return;
        group.plots.delete(plot);
    }

    _onXDomainChange(groupName, sourcePlot, xDomain) {
        const group = this.groups.get(groupName);
        if (!group) return;
        group.xDomain = xDomain;
        group.plots.forEach(plot => {
            if (plot !== sourcePlot) {
                plot.setXDomain(xDomain, { suppressEvent: true });
            }
        });
    }

    _onCrosshairXChange(groupName, sourcePlot, crosshairX) {
        const group = this.groups.get(groupName);
        if (!group) return;
        group.crosshairX = crosshairX;
        group.plots.forEach(plot => {
            if (plot === sourcePlot) return;
            this._applyCrosshair(plot, crosshairX);
        });
    }
}

// Maps the element_type field of report elements to the class rendering
// that element type. ReportView instantiates it with the element's root
// div and the shared report context, and drives it via update()/destroy().
const reportElementClassOf = {
    markdown: Markdown,
    html: Html,
    preformatted_text: PreformattedText,
    svg: Svg,
    passfail: PassFail,
    plot2d: Plot2d,
}

export class ReportView {
    constructor(resContent) {
        this.resContent = resContent;
        this.renderers = [];
        this.reportContext = {
            plotGroups: new ReportPlotGroups(),
        };
    }

    update(msgData) {
        const elements = msgData.elements || [];
        const oldRenderers = this.renderers;
        this.renderers = [];

        const report = document.createElement('div');
        report.classList.add('report-view');
        if (msgData.fill_height) {
            report.classList.add('report-view-fill');
        }

        elements.forEach((elementData, i) => {
            const elementRoot = document.createElement('div');
            elementRoot.classList.add('report-element');
            if (elementData.element_type === 'plot2d') {
                elementRoot.classList.add('report-element-plot2d');
            }
            report.appendChild(elementRoot);

            const elementClass =
                reportElementClassOf[elementData.element_type];

            if (!elementClass) {
                const pre = document.createElement('pre');
                pre.innerText =
                    'no handler found for report element type '
                    + elementData.element_type;
                elementRoot.replaceChildren(pre);
                return;
            }

            // Reuse existing renderer if same type at same index
            let renderer;
            const old = oldRenderers[i];
            if (old instanceof elementClass) {
                renderer = old;
                renderer.container = elementRoot;
                oldRenderers[i] = null;
            } else {
                old?.destroy?.();
                oldRenderers[i] = null;
                renderer = new elementClass(
                    elementRoot, this.reportContext
                );
            }
            renderer.update(elementData);
            this.renderers.push(renderer);
        });

        // Destroy any leftover old renderers
        for (const r of oldRenderers) {
            r?.destroy?.();
        }

        this.resContent.replaceChildren(report);
    }

    destroy() {
        for (const r of this.renderers) {
            r?.destroy?.();
        }
        this.renderers = [];
    }
}
