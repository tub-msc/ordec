// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// To be improved. Consider the constructor-only classes stubs for future functions.

import * as d3 from "d3";
import { LayoutGL } from './layout-gl.js';
import { SimPlot } from './simplot.js';
import { HierSelector } from './hier-selector.js';

let idCounter = 0;
export function generateId() {
    idCounter += 1;
    return "idgen" + idCounter;
}

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

function simpleReportElementClass(renderNode) {
    return class {
        constructor(container) {
            this.container = container;
        }

        update(msgData) {
            this.container.replaceChildren(renderNode(msgData));
        }
    };
}

const reportElementClassOf = {
    markdown: simpleReportElementClass((msgData) => {
        const section = document.createElement('div');
        section.classList.add('report-markdown');
        section.innerHTML = msgData.html;
        return section;
    }),
    preformatted_text: simpleReportElementClass((msgData) => {
        const pre = document.createElement('pre');
        pre.classList.add('report-preformatted');
        pre.innerText = msgData.text;
        return pre;
    }),
    svg: simpleReportElementClass((msgData) => {
        const svg = d3.create("svg")
            .attr("class", "report-svg")
            .attr("viewBox", msgData.viewbox);
        svg.attr("width", msgData.width);
        svg.attr("height", msgData.height);
        svg.append("g").html(msgData.inner);
        return svg.node();
    }),
    plot2d: class {
        constructor(container, reportContext) {
            this.container = container;
            this.reportContext = reportContext;
            this.plot = null;
            this.savedHidden = null;
            this.savedZoom = null;
        }

        update(msgData) {
            if (this.plot) {
                this.savedHidden = this.plot.getHiddenNames();
                this.savedZoom = this.plot.getZoomState();
            }
            this.destroy();

            const root = document.createElement('div');
            root.classList.add('report-plot2d');
            this.container.replaceChildren(root);

            this.plot = new SimPlot(root, {
                xlabel: msgData.xlabel,
                ylabel: msgData.ylabel,
                xscale: msgData.xscale,
                yscale: msgData.yscale,
                fixedHeight: msgData.height,
            });

            this.plot.setData(msgData.x, msgData.series);
            if (this.savedHidden) {
                this.plot.setHiddenNames(this.savedHidden);
            }
            if (this.savedZoom) {
                this.plot.setZoomState(this.savedZoom);
            }
            if (this.reportContext) {
                this.reportContext.plotGroups.register(
                    this.plot,
                    msgData.plot_group
                );
            }
        }

        destroy() {
            if (!this.plot) return;
            if (this.reportContext) {
                this.reportContext.plotGroups.unregister(this.plot);
            }
            this.plot.destroy();
            this.plot = null;
        }
    },
};

const viewClassOf = {
    html: class {
        constructor(resContent) {
            this.resContent = resContent;
        }

        update(msgData) {
            this.resContent.innerHTML = msgData;
        }
    },
    svg: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.transform = d3.zoomIdentity;
            this.tooltip = document.createElement('div');
            this.tooltip.classList.add('schem-tooltip');
            this.coordsDisplay = document.createElement('div');
            this.coordsDisplay.classList.add('schem-coords');
            this.resContent.append(this.tooltip, this.coordsDisplay);
        }
        zoomed({transform}) {
            this.transform = transform;
            this.g.attr("transform", transform);
        }
        _svgTextContent(textEl) {
            const tspans = textEl.querySelectorAll('tspan');
            if (tspans.length === 0) return textEl.textContent;
            return Array.from(tspans, t => t.textContent).join('\n');
        }
        _toSchemCoords(event) {
            const ctm = this.svgNode.getScreenCTM().inverse();
            const svgPt = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm);
            const [gx, gy] = this.transform.invert([svgPt.x, svgPt.y]);
            return [gx, this.yFlipOffset - gy];
        }
        _setupTooltips() {
            const tooltip = this.tooltip;
            const svgTextContent = this._svgTextContent;

            this.g.selectAll('.symbolOutline').each(function() {
                const group = this.parentNode;
                const cellNameEl = group.querySelector('.cellName');
                const paramsEl = group.querySelector('.params');
                if (!cellNameEl && !paramsEl) return;

                const content = document.createDocumentFragment();
                if (cellNameEl) {
                    const span = document.createElement('span');
                    span.className = 'schem-tooltip-cellname';
                    span.textContent = svgTextContent(cellNameEl);
                    content.appendChild(span);
                }
                if (paramsEl) {
                    const text = svgTextContent(paramsEl);
                    if (text) {
                        const span = document.createElement('span');
                        span.className = 'schem-tooltip-params';
                        span.textContent = text;
                        content.appendChild(span);
                    }
                }
                if (content.childNodes.length === 0) return;

                function positionTooltip(event) {
                    const rect = tooltip.parentNode.getBoundingClientRect();
                    tooltip.style.left = (event.clientX - rect.left + 12) + 'px';
                    tooltip.style.top = (event.clientY - rect.top + 12) + 'px';
                }

                d3.select(group)
                    .on('mouseenter', (event) => {
                        tooltip.replaceChildren(content.cloneNode(true));
                        tooltip.style.display = 'block';
                        positionTooltip(event);
                    })
                    .on('mousemove', (event) => positionTooltip(event))
                    .on('mouseleave', () => {
                        tooltip.style.display = 'none';
                    });
            });
        }
        update(msgData) {
            const viewbox = msgData['viewbox'];
            // Recover the Y-flip offset (uy+ly) from the viewBox
            this.yFlipOffset = 2 * viewbox[1] + viewbox[3];
            const viewbox2 = [[viewbox[0], viewbox[1]], [viewbox[2], viewbox[3]]]

            const svg = d3.create("svg")
                .attr("class", "fit")
                .attr("viewBox", viewbox);

            this.g = svg.append("g")
                .html(msgData['inner'])

            let zoom = d3.zoom()
                .extent(viewbox2)
                .scaleExtent([1, 12])
                .translateExtent(viewbox2);

            svg.call(zoom.transform, this.transform);
            this.g.attr("transform", this.transform);

            svg.call(zoom.on("zoom", (x) => this.zoomed(x)));

            this.svgNode = svg.node();
            const coordsDisplay = this.coordsDisplay;
            const self = this;
            svg.on('mousemove', (event) => {
                const [x, y] = self._toSchemCoords(event);
                coordsDisplay.textContent = `x: ${Math.round(x)}  y: ${Math.round(y)}`;
            });
            svg.on('mouseleave', () => {
                coordsDisplay.textContent = '';
            });

            this.resContent.replaceChildren(this.svgNode);
            this.resContent.append(this.tooltip, this.coordsDisplay);
            this._setupTooltips();
        }
    },
    report: class {
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
                    if (old && typeof old.destroy === 'function') {
                        old.destroy();
                    }
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
                if (r && typeof r.destroy === 'function') r.destroy();
            }

            this.resContent.replaceChildren(report);
        }
    },
    layout_gl: LayoutGL,
}

export class ResultViewer {
    static refreshAll = false;
    static useHierSelector = true;

    constructor(container, state) {
        this.container = container;
        container.element.innerHTML = `
            <div class="resview">
                <div class="resviewhead"></div>
                <div class="reswrapper">
                    <div class="resoverlay-topleft refreshing"><img src="/loading.gif" /> Refreshing view...</div>
                    <div class="resoverlay-topleft refreshable">View is out of date. <button>Refresh</button></div>
                    <div class="rescontent" tabindex="1"></div>
                    <div class="resexception"></div>
                </div>
            </div>
        `;
        this.resizeWithContainerAutomatically = true;
        this.resOverlayRefreshing = container.element.querySelector(".refreshing");
        this.resOverlayRefreshable = container.element.querySelector(".refreshable");
        container.element.querySelector(".refreshable button").onclick =
            () => this.refreshOnClick();
        this.showRefreshOverlay(null);
        this.resContent = container.element.querySelector(".rescontent");
        this.resWrapper = container.element.querySelector(".reswrapper");
        this.resException = container.element.querySelector(".resexception");
        this.resViewHead = container.element.querySelector(".resviewhead");
        this.viewUpToDate = false;
        this.viewSelected = null;
        this.refreshRequestedByUser = false;
        this._useHier = ResultViewer.useHierSelector;
        if (this._useHier) {
            this.hierSelector = new HierSelector(this.resViewHead, {
                onSelect: (viewName) => this._onViewSelected(viewName),
                onDeselect: () => this._onViewDeselected(),
            });
            this.viewSelector = null;
        } else {
            this._createFlatSelector();
        }
        if (state['view']) {
            this.restoreSelectedView = state['view'];
        }
        //this.updateGlobalState();
        this.viewListInitialized = false;
    }

    _createFlatSelector() {
        const sel = document.createElement('select');
        sel.classList.add('viewsel');
        this.resViewHead.appendChild(sel);
        this.viewSelector = sel;
        this.viewSelector.onchange = () => this.viewSelectorOnChange();
        this.hierSelector = null;
    }

    refreshOnClick() {
        this.refreshRequestedByUser = true;
        this.showRefreshOverlay('refreshing');
        this.client.requestNextView();
    }

    showRefreshOverlay(config) {
        this.resOverlayRefreshable.style.display = (config == 'refreshable')?'':'none';
        this.resOverlayRefreshing.style.display = (config == 'refreshing')?'':'none';
    }

    requestsView() {
        if(!this.viewSelected) {
            return false;
        }
        return (!this.viewUpToDate) && (
            this.refreshRequestedByUser ||
            this.viewInfo().auto_refresh ||
            ResultViewer.refreshAll
            );
    }

    viewInfo() {
        let info = this.client.views.get(this.viewSelected);
        if(info) {
            return info;
        } else {
            return {};
        }
    }

    resetResContent() {
        // Replace the rescontent div with a fresh rescontent div, mainly
        // to clear any event handlers that might have been attached to the
        // resContent previously.
        const resContentNew = document.createElement('div');
        resContentNew.classList.add('rescontent');
        resContentNew.tabIndex = "0";
        this.resWrapper.replaceChild(resContentNew, this.resContent);
        this.resContent = resContentNew;
    }

    viewSelectorOnChange() {
        const viewName = this.viewSelector.options[this.viewSelector.selectedIndex].value;
        this._onViewSelected(viewName);
    }

    _onViewSelected(viewName) {
        this.viewSelected = viewName;
        this.container.setState({ view: viewName });
        this.container.setTitle(viewName);

        this.invalidate();
        this.resetResContent();
        this.resContent.focus();
        this.view = null;
        this.client.requestNextView();
    }

    _onViewDeselected() {
        this.viewSelected = null;
        this.viewUpToDate = false;
        this.view = null;
        this.container.setTitle('Result View');
        this.showRefreshOverlay(null);
        this.showException(null);
        this.resetResContent();
    }

    invalidate() {
        this.viewUpToDate = false;
        this.refreshRequestedByUser = false;

        this.updateOverlay();
    }

    updateOverlay() {
        if((!this.viewSelected) || this.viewUpToDate) {
            this.showRefreshOverlay(null);
        } else if(this.viewInfo().auto_refresh && !ResultViewer.refreshAll) {
            this.showRefreshOverlay("refreshing");
        } else {
            this.showRefreshOverlay("refreshable");
        }
    }

    updateViewList() {
        // Check if mode toggled at runtime
        if (this._useHier !== ResultViewer.useHierSelector) {
            this._useHier = ResultViewer.useHierSelector;
            this.resViewHead.replaceChildren();
            if (this._useHier) {
                this.viewSelector = null;
                this.hierSelector = new HierSelector(this.resViewHead, {
                    onSelect: (viewName) => this._onViewSelected(viewName),
                });
            } else {
                this.hierSelector = null;
                this._createFlatSelector();
            }
        }

        const viewNames = [];
        this.client.views.forEach(view => viewNames.push(view.name));

        const prevSelected = this.viewSelected || this.restoreSelectedView;

        if (this._useHier) {
            this.hierSelector.update(viewNames, prevSelected);
            this.viewSelected = this.hierSelector.selectedView;
        } else {
            let vs = this.viewSelector;
            vs.innerHTML = "<option disabled selected value>--- Select result from list ---</option>";
            let selectedVal = null;
            this.client.views.forEach(view => {
                var option = document.createElement("option");
                option.innerText = view.name;
                option.value = view.name;
                vs.appendChild(option);
                if (view.name == prevSelected) {
                    option.selected = true;
                    selectedVal = view.name;
                }
            });
            this.viewSelected = selectedVal;
        }
        if (this.viewSelected) {
            this.container.setTitle(this.viewSelected);
        }
        this.viewListInitialized = true;
    }

    updateViewListAndException() {
        this.updateViewList();
        if (this.client.exception) {
            // In this case, the exception was generated during module evaluation:
            this.showRefreshOverlay(null);
            this.showException(this.client.exception);
        } else {
            this.showException(null);
            this.invalidate();
            this.updateOverlay();
        }
    }

    registerClient(client) {
        this.client = client;
        this.updateViewList();
    }

    showException(text) {
        this.resException.style.display = text?'':'none';
        this.resContent.style.display = text?'none':'';

        if(text) {
            let pre = document.createElement("pre");
            pre.innerText = text;
            pre.classList.add('exception');
            this.resException.replaceChildren(pre);
        }
    }

    updateView(msg) {
        //this.resContent.replaceChildren();
        this.viewUpToDate = true;
        this.showRefreshOverlay(null);

        if(msg.exception) {
            // In this case, the exception was generated during view generation:
            this.showException(msg.exception);
        } else {
            this.showException(null);
            const viewClass = viewClassOf[msg.type];
            if(!viewClass) {
                let pre = document.createElement("pre");
                pre.innerText = 'no handler found for type ' + msg.type;
                this.resContent.replaceChildren(pre);
            } else if(this.view instanceof viewClass) {
                this.view.update(msg.data);
            } else {
                this.view = new viewClass(this.resContent);
                this.view.update(msg.data);
            }
        }

        this.updateOverlay();
    }

    testInfo() {
        // For automated browser testing (see test_web.py).
        const r = this.resContent.getBoundingClientRect();
        return {
            html: this.resContent.innerHTML,
            top: r.top,
            right: r.right,
            bottom: r.bottom,
            left: r.left,
            width: r.width,
            height: r.height,
        };
    }
}
