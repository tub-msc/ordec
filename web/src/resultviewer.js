// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// To be improved. Consider the constructor-only classes stubs for future functions.

import * as d3 from "d3";
import { LayoutGL } from './layout-gl.js';
import { SimPlot } from './simplot.js';
import { HierSelector } from './hier-selector.js';
import { viewEventBus } from './event-bus.js';

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
    html: simpleReportElementClass((msgData) => {
        const section = document.createElement('div');
        section.classList.add('report-html');
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
    svg: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.transform = d3.zoomIdentity;
            this.tooltip = document.createElement('div');
            this.tooltip.classList.add('schem-error-tooltip');
            this.highlightOverlay = null;
            this.svg = null;

            this._onLvsSelect = (data) => this.setHighlight(data);
            this._onLvsClear = () => this.clearHighlight();
            viewEventBus.on('lvs:select', this._onLvsSelect);
            viewEventBus.on('lvs:clear', this._onLvsClear);

            const pending = viewEventBus.consumePending('lvs:select');
            if (pending) {
                this._pendingHighlight = pending;
            }
        }
        zoomed({transform}) {
            this.transform = transform;
            this.g.attr("transform", transform);
        }
        setHighlight(data) {
            this.clearHighlight();
            if (!this.svg || !data.schem_path || data.schem_path.length === 0) {
                return;
            }

            const highlightGroup = this.svg.append("g")
                .attr("class", "lvs-highlight-group")
                .attr("transform", this.transform);

            const instName = data.schem_path.join('.');
            const instGroup = this.g.select(`[data-inst="${instName}"]`);

            if (instGroup.empty()) {
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
                .attr("fill", "none")
                .attr("stroke", "#e55")
                .attr("stroke-width", 0.15)
                .attr("stroke-dasharray", "0.3,0.15");

            this.highlightOverlay = highlightGroup;
        }
        clearHighlight() {
            if (this.highlightOverlay) {
                this.highlightOverlay.remove();
                this.highlightOverlay = null;
            }
        }
        update(msgData) {
            const viewbox = msgData['viewbox'];
            const viewbox2 = [[viewbox[0], viewbox[1]], [viewbox[2], viewbox[3]]]

            const svg = d3.create("svg")
                .attr("class", "fit")
                .attr("viewBox", viewbox);
            this.svg = svg;

            this.g = svg.append("g")
                .html(msgData['inner'])

            let zoom = d3.zoom()
                .extent(viewbox2)
                .scaleExtent([1, 12])
                .translateExtent(viewbox2);

            svg.call(zoom.transform, this.transform);
            this.g.attr("transform", this.transform);

            svg.call(zoom.on("zoom", (x) => this.zoomed(x)));

            this.resContent.replaceChildren(svg.node(), this.tooltip);

            svg.selectAll('.errorMarker')
                .on('mouseover', (event) => {
                    const msg = event.target.getAttribute('data-error');
                    this.tooltip.textContent = msg;
                    this.tooltip.style.display = 'block';
                })
                .on('mousemove', (event) => {
                    const rect = this.resContent.getBoundingClientRect();
                    this.tooltip.style.left = (event.clientX - rect.left + 10) + 'px';
                    this.tooltip.style.top = (event.clientY - rect.top + 10) + 'px';
                })
                .on('mouseout', () => {
                    this.tooltip.style.display = 'none';
                });

            if (this._pendingHighlight) {
                this.setHighlight(this._pendingHighlight);
                this._pendingHighlight = null;
            }
        }
        destroy() {
            viewEventBus.off('lvs:select', this._onLvsSelect);
            viewEventBus.off('lvs:clear', this._onLvsClear);
            this.clearHighlight();
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
    },
    layout_gl: LayoutGL,
    drc_report: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.el = document.createElement('div');
            this.el.className = 'drc-viewer';
            this.selectedItemNid = null;
            resContent.appendChild(this.el);
        }

        update(data) {
            const catMap = new Map();
            data.categories.forEach(cat => {
                catMap.set(cat.nid, { ...cat, items: [], count: 0 });
            });

            const itemMap = new Map();
            data.items.forEach(item => {
                itemMap.set(item.nid, item);
                const cat = catMap.get(item.category_nid);
                if (cat) {
                    cat.items.push(item);
                    cat.count++;
                }
            });

            const totalCount = data.items.length;
            const catCount = data.categories.length;

            let html = `<div class="drc-header">
                <span>${totalCount} violations in ${catCount} categories</span>
                <button class="drc-deselect" disabled>Deselect</button>
            </div>`;
            html += '<div class="drc-categories">';

            data.categories.forEach(cat => {
                const catData = catMap.get(cat.nid);
                html += `<div class="drc-category" data-nid="${cat.nid}">`;
                html += `<span class="drc-category-toggle">&#9654;</span> `;
                html += `<span class="drc-category-name">${cat.name}</span>`;
                html += ` <span class="drc-category-count">(${catData.count})</span>`;
                if (cat.description) {
                    html += `<span class="drc-category-desc"> - ${cat.description}</span>`;
                }
                html += '<div class="drc-items">';
                catData.items.forEach((item, idx) => {
                    const label = item.shapes.length > 0
                        ? item.shapes[0].type
                        : 'item';
                    html += `<div class="drc-item" data-nid="${item.nid}">#${idx + 1}: ${label}</div>`;
                });
                html += '</div></div>';
            });

            html += '</div>';
            this.el.innerHTML = html;

            this.el.querySelectorAll('.drc-category').forEach(catEl => {
                const toggleCategory = () => {
                    catEl.classList.toggle('expanded');
                    const toggle = catEl.querySelector('.drc-category-toggle');
                    toggle.innerHTML = catEl.classList.contains('expanded') ? '&#9660;' : '&#9654;';
                };
                catEl.addEventListener('click', (e) => {
                    if (!e.target.classList.contains('drc-item')) {
                        toggleCategory();
                    }
                });
            });

            const deselectBtn = this.el.querySelector('.drc-deselect');
            const deselect = () => {
                this.el.querySelectorAll('.drc-item.selected').forEach(el => {
                    el.classList.remove('selected');
                });
                this.selectedItemNid = null;
                deselectBtn.disabled = true;
                viewEventBus.emit('drc:clear');
            };
            deselectBtn.addEventListener('click', deselect);

            this.el.querySelectorAll('.drc-item').forEach(itemEl => {
                itemEl.addEventListener('click', () => {
                    this.el.querySelectorAll('.drc-item.selected').forEach(el => {
                        el.classList.remove('selected');
                    });
                    itemEl.classList.add('selected');
                    deselectBtn.disabled = false;
                    const nid = parseInt(itemEl.dataset.nid, 10);
                    this.selectedItemNid = nid;
                    const item = itemMap.get(nid);
                    if (item) {
                        const payload = { shapes: item.shapes };
                        if (viewEventBus.hasListeners('drc:select')) {
                            viewEventBus.emit('drc:select', payload);
                        } else {
                            viewEventBus.setPending('drc:select', payload);
                            const layoutView = this.viewName ? `${this.viewName}.ref_layout` : null;
                            viewEventBus.emit('layout:request-open', {
                                view: layoutView,
                                sourceContainer: this.glContainer,
                            });
                        }
                    }
                });
            });

            this.itemMap = itemMap;
        }

        destroy() {
            viewEventBus.emit('drc:clear');
        }
    },
    lvs_report: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.el = document.createElement('div');
            this.el.className = 'lvs-viewer';
            this.selectedItemNid = null;
            resContent.appendChild(this.el);
        }

        update(data) {
            const circuitMap = new Map();
            data.circuits.forEach(circuit => {
                circuitMap.set(circuit.nid, { ...circuit, items: [] });
            });

            const itemMap = new Map();
            data.items.forEach(item => {
                itemMap.set(item.nid, item);
                const circuit = circuitMap.get(item.circuit_nid);
                if (circuit) {
                    circuit.items.push(item);
                }
            });

            const mismatchItemCount = data.items.filter(i => i.status !== 'match').length;
            const circuitMismatchCount = data.circuits.filter(c => c.status !== 'match').length;

            const statusClass = data.status === 'match' ? 'lvs-pass' : 'lvs-fail';
            const statusText = data.status === 'match' ? 'PASS' : 'FAIL';

            let summaryText;
            if (circuitMismatchCount > 0) {
                summaryText = `${circuitMismatchCount} circuit${circuitMismatchCount > 1 ? 's' : ''} with errors`;
                if (mismatchItemCount > 0) {
                    summaryText += `, ${mismatchItemCount} item mismatch${mismatchItemCount > 1 ? 'es' : ''}`;
                }
            } else {
                summaryText = 'All circuits match';
            }

            let html = `<div class="lvs-header ${statusClass}">
                <span class="lvs-status">${statusText}</span>
                <span class="lvs-summary">${summaryText}</span>
                <button class="lvs-deselect" disabled>Deselect</button>
            </div>`;
            html += '<div class="lvs-circuits">';

            data.circuits.forEach(circuit => {
                const circuitData = circuitMap.get(circuit.nid);
                const mismatchItems = circuitData.items.filter(i => i.status !== 'match');

                if (circuit.status === 'match' && mismatchItems.length === 0) {
                    return;
                }

                const circuitStatusClass = circuit.status === 'match' ? 'lvs-match' : 'lvs-mismatch';
                const circuitName = circuit.layout_name || circuit.schem_name || 'unknown';
                const hasExpandableItems = mismatchItems.length > 0;

                html += `<div class="lvs-circuit ${circuitStatusClass}" data-nid="${circuit.nid}">`;
                if (hasExpandableItems) {
                    html += `<span class="lvs-circuit-toggle">&#9654;</span> `;
                }
                html += `<span class="lvs-circuit-name">${circuitName}</span>`;

                if (circuit.status !== 'match' && circuit.message) {
                    html += `<div class="lvs-circuit-msg">${circuit.message}</div>`;
                }

                if (hasExpandableItems) {
                    html += '<div class="lvs-items">';
                    mismatchItems.forEach((item, idx) => {
                        const typeLabel = item.item_type;
                        const layoutId = item.layout_name || '?';
                        const schemId = item.schem_name || '?';
                        html += `<div class="lvs-item lvs-item-mismatch" data-nid="${item.nid}">`;
                        html += `${typeLabel}: L:${layoutId} ↔ S:${schemId}`;
                        if (item.message) {
                            html += ` <span class="lvs-item-msg">${item.message}</span>`;
                        }
                        html += '</div>';
                    });
                    html += '</div>';
                }

                html += '</div>';
            });

            html += '</div>';
            this.el.innerHTML = html;

            this.el.querySelectorAll('.lvs-circuit').forEach(circuitEl => {
                const toggleCircuit = () => {
                    circuitEl.classList.toggle('expanded');
                    const toggle = circuitEl.querySelector('.lvs-circuit-toggle');
                    toggle.innerHTML = circuitEl.classList.contains('expanded') ? '&#9660;' : '&#9654;';
                };
                circuitEl.addEventListener('click', (e) => {
                    if (!e.target.classList.contains('lvs-item')) {
                        toggleCircuit();
                    }
                });
            });

            const deselectBtn = this.el.querySelector('.lvs-deselect');
            const deselect = () => {
                this.el.querySelectorAll('.lvs-item.selected').forEach(el => {
                    el.classList.remove('selected');
                });
                this.selectedItemNid = null;
                deselectBtn.disabled = true;
                viewEventBus.emit('lvs:clear');
            };
            deselectBtn.addEventListener('click', deselect);

            this.el.querySelectorAll('.lvs-item').forEach(itemEl => {
                itemEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.el.querySelectorAll('.lvs-item.selected').forEach(el => {
                        el.classList.remove('selected');
                    });
                    itemEl.classList.add('selected');
                    deselectBtn.disabled = false;
                    const nid = parseInt(itemEl.dataset.nid, 10);
                    this.selectedItemNid = nid;
                    const item = itemMap.get(nid);
                    if (item) {
                        const payload = {
                            shapes: item.layout_shapes || [],
                            schem_path: item.schem_path || [],
                        };

                        const hasLayoutShapes = item.layout_shapes && item.layout_shapes.length > 0;
                        const hasSchemPath = item.schem_path && item.schem_path.length > 0;
                        const hasListeners = viewEventBus.hasListeners('lvs:select');

                        console.log('LVS click:', {
                            viewName: this.viewName,
                            hasLayoutShapes,
                            hasSchemPath,
                            hasListeners,
                            schem_path_raw: item.schem_path,
                            layout_shapes_raw: item.layout_shapes,
                            item,
                        });

                        if (hasListeners) {
                            viewEventBus.emit('lvs:select', payload);
                        } else {
                            viewEventBus.setPending('lvs:select', payload);
                            if (hasLayoutShapes) {
                                const layoutView = this.viewName ? `${this.viewName}.ref_layout` : null;
                                console.log('Requesting layout:', layoutView);
                                viewEventBus.emit('layout:request-open', {
                                    view: layoutView,
                                    sourceContainer: this.glContainer,
                                });
                            }
                            if (hasSchemPath) {
                                const schemView = this.viewName ? `${this.viewName}.ref_schematic` : null;
                                console.log('Requesting schematic:', schemView);
                                viewEventBus.emit('schematic:request-open', {
                                    view: schemView,
                                    sourceContainer: this.glContainer,
                                });
                            }
                        }
                    }
                });
            });

            this.itemMap = itemMap;
        }

        destroy() {
            viewEventBus.emit('lvs:clear');
        }
    },
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
                    <div class="resview-empty">Select a view from the dropdown above</div>
                </div>
            </div>
        `;
        container.addEventListener('beforeComponentRelease', () => {
            this.view?.destroy?.();
        });
        this.resizeWithContainerAutomatically = true;
        this.resOverlayRefreshing = container.element.querySelector(".refreshing");
        this.resOverlayRefreshable = container.element.querySelector(".refreshable");
        container.element.querySelector(".refreshable button").onclick =
            () => this.refreshOnClick();
        this.showRefreshOverlay(null);
        this.resContent = container.element.querySelector(".rescontent");
        this.resWrapper = container.element.querySelector(".reswrapper");
        this.resException = container.element.querySelector(".resexception");
        this.resEmpty = container.element.querySelector(".resview-empty");
        this.resViewHead = container.element.querySelector(".resviewhead");
        this.viewUpToDate = false;
        this.viewSelected = null;
        this.refreshRequestedByUser = false;
        this.directView = state && state.directView;

        if (this.directView) {
            const label = document.createElement('span');
            label.className = 'direct-view-label';
            label.textContent = state.view;
            this.resViewHead.appendChild(label);
            this.hierSelector = null;
            this.viewSelector = null;
            this.viewSelected = state.view;
            this.resEmpty.style.display = 'none';
        } else {
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
            if (state && state['view']) {
                this.restoreSelectedView = state['view'];
            }
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
        if (this.directView) {
            return !this.viewUpToDate;
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
        this.resEmpty.style.display = 'none';

        this.invalidate();
        this.resetResContent();
        this.resContent.focus();
        this.view?.destroy?.();
        this.view = null;
        this.client.requestNextView();
    }

    _onViewDeselected() {
        this.viewSelected = null;
        this.viewUpToDate = false;
        this.view?.destroy?.();
        this.view = null;
        this.container.setTitle('Result View');
        this.showRefreshOverlay(null);
        this.showException(null);
        this.resetResContent();
        this.resEmpty.style.display = '';
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
        if (this.directView) {
            this.container.setTitle(this.viewSelected);
            this.viewListInitialized = true;
            return;
        }

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
            this.resEmpty.style.display = 'none';
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
                this.view.viewName = this.viewSelected;
                this.view.glContainer = this.container;
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
