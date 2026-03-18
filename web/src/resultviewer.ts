// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// To be improved. Consider the constructor-only classes stubs for future functions.

import * as d3 from "d3";
import { LayoutGL } from './layout-gl';
import { SimPlot } from './simplot';
import { HierSelector } from './hier-selector';
import type { OrdecClient, ResultViewerLike } from './client';
import type {
    ViewClass, ViewInstance, ReportElementClass,
    ReportElementInstance, ReportContext, SyncablePlot
} from './types';

let idCounter = 0;
export function generateId(): string {
    idCounter += 1;
    return "idgen" + idCounter;
}

class ReportPlotGroups {
    groups: Map<string, { plots: Set<SyncablePlot>; xDomain: number[] | null; crosshairX: number | null | undefined }>;
    groupNameOfPlot: Map<SyncablePlot, string>;

    constructor() {
        this.groups = new Map();
        this.groupNameOfPlot = new Map();
    }

    _applyCrosshair(plot: SyncablePlot, crosshairX: number | null): void {
        if (crosshairX === null) {
            plot.clearCrosshair({ suppressEvent: true });
        } else {
            plot.setCrosshairX(crosshairX, { suppressEvent: true });
        }
    }

    register(plot: SyncablePlot, groupName: string | undefined): void {
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
            onXDomainChange: (xDomain: number[]) => this._onXDomainChange(groupName, plot, xDomain),
            onCrosshairXChange: (crosshairX: number | null) => this._onCrosshairXChange(groupName, plot, crosshairX),
        });
        if (!group.xDomain) {
            group.xDomain = plot.getXDomain();
        }

        if (group.xDomain) {
            plot.setXDomain(group.xDomain, { suppressEvent: true });
        }
        if (group.crosshairX !== undefined) {
            this._applyCrosshair(plot, group.crosshairX!);
        }
    }

    unregister(plot: SyncablePlot): void {
        const groupName = this.groupNameOfPlot.get(plot);
        if (!groupName) return;
        this.groupNameOfPlot.delete(plot);

        const group = this.groups.get(groupName);
        if (!group) return;
        group.plots.delete(plot);
    }

    _onXDomainChange(groupName: string, sourcePlot: SyncablePlot, xDomain: number[]): void {
        const group = this.groups.get(groupName);
        if (!group) return;
        group.xDomain = xDomain;
        group.plots.forEach(plot => {
            if (plot !== sourcePlot) {
                plot.setXDomain(xDomain, { suppressEvent: true });
            }
        });
    }

    _onCrosshairXChange(groupName: string, sourcePlot: SyncablePlot, crosshairX: number | null): void {
        const group = this.groups.get(groupName);
        if (!group) return;
        group.crosshairX = crosshairX;
        group.plots.forEach(plot => {
            if (plot === sourcePlot) return;
            this._applyCrosshair(plot, crosshairX);
        });
    }
}

function simpleReportElementClass(renderNode: (msgData: any) => HTMLElement | SVGElement): ReportElementClass {
    return class {
        container: HTMLElement;

        constructor(container: HTMLElement) {
            this.container = container;
        }

        update(msgData: any): void {
            this.container.replaceChildren(renderNode(msgData));
        }
    };
}

const reportElementClassOf: Record<string, ReportElementClass> = {
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
        return svg.node()!;
    }),
    plot2d: class {
        container: HTMLElement;
        reportContext: ReportContext | undefined;
        plot: SimPlot | null;
        savedHidden: Set<string> | null;
        savedZoom: any;

        constructor(container: HTMLElement, reportContext?: ReportContext) {
            this.container = container;
            this.reportContext = reportContext;
            this.plot = null;
            this.savedHidden = null;
            this.savedZoom = null;
        }

        update(msgData: any): void {
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

        destroy(): void {
            if (!this.plot) return;
            if (this.reportContext) {
                this.reportContext.plotGroups.unregister(this.plot);
            }
            this.plot.destroy();
            this.plot = null;
        }
    },
};

const viewClassOf: Record<string, any> = {
    html: class {
        resContent: HTMLElement;

        constructor(resContent: HTMLElement) {
            this.resContent = resContent;
        }

        update(msgData: string): void {
            this.resContent.innerHTML = msgData;
        }
    },
    svg: class {
        resContent: HTMLElement;
        transform: d3.ZoomTransform;
        g: d3.Selection<SVGGElement, unknown, null, undefined>;

        constructor(resContent: HTMLElement) {
            this.resContent = resContent;
            this.transform = d3.zoomIdentity;
        }
        zoomed({transform}: {transform: d3.ZoomTransform}): void {
            this.transform = transform;
            this.g.attr("transform", transform as any);
        }
        update(msgData: any): void {
            const viewbox = msgData['viewbox'];
            const viewbox2: [[number, number], [number, number]] = [[viewbox[0], viewbox[1]], [viewbox[2], viewbox[3]]];

            const svg = d3.create("svg")
                .attr("class", "fit")
                .attr("viewBox", viewbox);

            this.g = svg.append("g")
                .html(msgData['inner']) as any;

            let zoom = d3.zoom<SVGSVGElement, unknown>()
                .extent(viewbox2)
                .scaleExtent([1, 12])
                .translateExtent(viewbox2);

            svg.call(zoom.transform, this.transform);
            this.g.attr("transform", this.transform as any);

            svg.call(zoom.on("zoom", (x) => this.zoomed(x)));

            this.resContent.replaceChildren(svg.node()!);
        }
    },
    report: class {
        resContent: HTMLElement;
        renderers: ReportElementInstance[];
        reportContext: ReportContext;

        constructor(resContent: HTMLElement) {
            this.resContent = resContent;
            this.renderers = [];
            this.reportContext = {
                plotGroups: new ReportPlotGroups(),
            };
        }

        update(msgData: any): void {
            const elements: any[] = msgData.elements || [];
            const oldRenderers = this.renderers;
            this.renderers = [];

            const report = document.createElement('div');
            report.classList.add('report-view');
            if (msgData.fill_height) {
                report.classList.add('report-view-fill');
            }

            elements.forEach((elementData: any, i: number) => {
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
                let renderer: ReportElementInstance;
                const old: any = oldRenderers[i];
                if (old instanceof elementClass) {
                    renderer = old;
                    renderer.container = elementRoot;
                    (oldRenderers as any)[i] = null;
                } else {
                    if (old && typeof old.destroy === 'function') {
                        old.destroy();
                    }
                    (oldRenderers as any)[i] = null;
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

interface GoldenLayoutContainer {
    element: HTMLElement;
    setState(state: Record<string, any>): void;
    setTitle(title: string): void;
}

export class ResultViewer implements ResultViewerLike {
    static refreshAll = false;
    static useHierSelector = true;

    container: GoldenLayoutContainer;
    resizeWithContainerAutomatically: boolean;
    resOverlayRefreshing: HTMLElement;
    resOverlayRefreshable: HTMLElement;
    resContent: HTMLElement;
    resWrapper: HTMLElement;
    resException: HTMLElement;
    resViewHead: HTMLElement;
    viewUpToDate: boolean;
    viewSelected: string | null;
    refreshRequestedByUser: boolean;
    _useHier: boolean;
    hierSelector: HierSelector | null;
    viewSelector: HTMLSelectElement | null;
    restoreSelectedView: string | undefined;
    viewListInitialized: boolean;
    client: OrdecClient;
    view: ViewInstance | null;

    constructor(container: GoldenLayoutContainer, state: Record<string, any>) {
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
        this.resOverlayRefreshing = container.element.querySelector(".refreshing")!;
        this.resOverlayRefreshable = container.element.querySelector(".refreshable")!;
        (container.element.querySelector(".refreshable button") as HTMLElement).onclick =
            () => this.refreshOnClick();
        this.showRefreshOverlay(null);
        this.resContent = container.element.querySelector(".rescontent")!;
        this.resWrapper = container.element.querySelector(".reswrapper")!;
        this.resException = container.element.querySelector(".resexception")!;
        this.resViewHead = container.element.querySelector(".resviewhead")!;
        this.viewUpToDate = false;
        this.viewSelected = null;
        this.refreshRequestedByUser = false;
        this._useHier = ResultViewer.useHierSelector;
        this.view = null;
        if (this._useHier) {
            this.hierSelector = new HierSelector(this.resViewHead, {
                onSelect: (viewName: string) => this._onViewSelected(viewName),
                onDeselect: () => this._onViewDeselected(),
            });
            this.viewSelector = null;
        } else {
            this._createFlatSelector();
            this.hierSelector = null;
        }
        if (state['view']) {
            this.restoreSelectedView = state['view'];
        }
        this.viewListInitialized = false;
    }

    _createFlatSelector(): void {
        const sel = document.createElement('select');
        sel.classList.add('viewsel');
        this.resViewHead.appendChild(sel);
        this.viewSelector = sel;
        this.viewSelector.onchange = () => this.viewSelectorOnChange();
        this.hierSelector = null;
    }

    refreshOnClick(): void {
        this.refreshRequestedByUser = true;
        this.showRefreshOverlay('refreshing');
        this.client.requestNextView();
    }

    showRefreshOverlay(config: string | null): void {
        this.resOverlayRefreshable.style.display = (config == 'refreshable')?'':'none';
        this.resOverlayRefreshing.style.display = (config == 'refreshing')?'':'none';
    }

    requestsView(): boolean {
        if(!this.viewSelected) {
            return false;
        }
        return (!this.viewUpToDate) && (
            this.refreshRequestedByUser ||
            this.viewInfo().auto_refresh ||
            ResultViewer.refreshAll
            );
    }

    viewInfo(): { auto_refresh?: boolean } {
        let info = this.client.views.get(this.viewSelected!);
        if(info) {
            return info;
        } else {
            return {};
        }
    }

    resetResContent(): void {
        // Replace the rescontent div with a fresh rescontent div, mainly
        // to clear any event handlers that might have been attached to the
        // resContent previously.
        const resContentNew = document.createElement('div');
        resContentNew.classList.add('rescontent');
        resContentNew.tabIndex = 0;
        this.resWrapper.replaceChild(resContentNew, this.resContent);
        this.resContent = resContentNew;
    }

    viewSelectorOnChange(): void {
        const viewName = this.viewSelector!.options[this.viewSelector!.selectedIndex].value;
        this._onViewSelected(viewName);
    }

    _onViewSelected(viewName: string): void {
        this.viewSelected = viewName;
        this.container.setState({ view: viewName });
        this.container.setTitle(viewName);

        this.invalidate();
        this.resetResContent();
        this.resContent.focus();
        this.view = null;
        this.client.requestNextView();
    }

    _onViewDeselected(): void {
        this.viewSelected = null;
        this.viewUpToDate = false;
        this.view = null;
        this.container.setTitle('Result View');
        this.showRefreshOverlay(null);
        this.showException(null);
        this.resetResContent();
    }

    invalidate(): void {
        this.viewUpToDate = false;
        this.refreshRequestedByUser = false;

        this.updateOverlay();
    }

    updateOverlay(): void {
        if((!this.viewSelected) || this.viewUpToDate) {
            this.showRefreshOverlay(null);
        } else if(this.viewInfo().auto_refresh && !ResultViewer.refreshAll) {
            this.showRefreshOverlay("refreshing");
        } else {
            this.showRefreshOverlay("refreshable");
        }
    }

    updateViewList(): void {
        // Check if mode toggled at runtime
        if (this._useHier !== ResultViewer.useHierSelector) {
            this._useHier = ResultViewer.useHierSelector;
            this.resViewHead.replaceChildren();
            if (this._useHier) {
                this.viewSelector = null;
                this.hierSelector = new HierSelector(this.resViewHead, {
                    onSelect: (viewName: string) => this._onViewSelected(viewName),
                });
            } else {
                this.hierSelector = null;
                this._createFlatSelector();
            }
        }

        const viewNames: string[] = [];
        this.client.views.forEach(view => viewNames.push(view.name));

        const prevSelected = this.viewSelected || this.restoreSelectedView;

        if (this._useHier) {
            this.hierSelector!.update(viewNames, prevSelected || null);
            this.viewSelected = this.hierSelector!.selectedView;
        } else {
            let vs = this.viewSelector!;
            vs.innerHTML = "<option disabled selected value>--- Select result from list ---</option>";
            let selectedVal: string | null = null;
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

    updateViewListAndException(): void {
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

    registerClient(client: OrdecClient): void {
        this.client = client;
        this.updateViewList();
    }

    showException(text: string | null): void {
        this.resException.style.display = text?'':'none';
        this.resContent.style.display = text?'none':'';

        if(text) {
            let pre = document.createElement("pre");
            pre.innerText = text;
            pre.classList.add('exception');
            this.resException.replaceChildren(pre);
        }
    }

    updateView(msg: any): void {
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
                this.view!.update(msg.data);
            }
        }

        this.updateOverlay();
    }

    testInfo(): { html: string; top: number; right: number; bottom: number; left: number; width: number; height: number } {
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
