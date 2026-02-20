// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// To be improved. Consider the constructor-only classes stubs for future functions.

import * as d3 from "d3";
import { LayoutGL } from './layout-gl.js';
import { SimPlot } from './simplot.js';

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
        if (group.plots.size === 0) {
            this.groups.delete(groupName);
        }
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
        }

        update(msgData) {
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
        }
        zoomed({transform}) {
            this.transform = transform;
            this.g.attr("transform", transform);
        }
        update(msgData) {
            const viewbox = msgData['viewbox'];
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

            this.resContent.replaceChildren(svg.node());
        }
    },
    report: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.renderers = [];
        }

        update(msgData) {
            this.renderers.forEach(renderer => {
                if (typeof renderer.destroy === 'function') {
                    renderer.destroy();
                }
            });
            this.renderers = [];

            const report = document.createElement('div');
            report.classList.add('report-view');
            const reportContext = {
                plotGroups: new ReportPlotGroups(),
            };

            (msgData.elements || []).forEach(elementData => {
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

                const renderer = new elementClass(elementRoot, reportContext);
                renderer.update(elementData);
                this.renderers.push(renderer);
            });

            this.resContent.replaceChildren(report);
        }
    },
    layout_gl: LayoutGL,
    dcsim: class {
        constructor(resContent) {
            this.resContent = resContent;
        }

        update(msgData) {
            let table = document.createElement('table');
            table.classList.add('dc_table');
            table.innerHTML = '<tr><th>Net</th><th>Voltage</th></tr>';
            msgData.dc_voltages.forEach(row => {
                let tr = document.createElement('tr');
                table.appendChild(tr);
                tr.innerHTML = `<td>${row[0]}</td><td>${row[1]}</td>`;
            });

            let table2 = document.createElement('table');
            table2.classList.add('dc_table');
            table2.innerHTML = '<tr><th>Branch</th><th>Current</th></tr>';
            msgData.dc_currents.forEach(row => {
                let tr = document.createElement('tr');
                table2.appendChild(tr);
                tr.innerHTML = `<td>${row[0]}</td><td>${row[1]}</td>`;
            });

            this.resContent.replaceChildren(
                table,
                document.createElement('br'),
                table2
            );
        }
    },
    dcsweep: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.plots = [];
        }

        update(msgData) {
            this.plots.forEach(p => p.destroy());
            this.plots = [];

            const container = document.createElement('div');
            container.classList.add('simplot-container');
            this.resContent.replaceChildren(container);

            const sweep = msgData.sweep;
            const sweepName = msgData.sweep_name || "Sweep";
            const voltages = msgData.voltages;
            const currents = msgData.currents;

            if (Object.keys(voltages).length > 0) {
                const plot = new SimPlot(container, {
                    xlabel: sweepName,
                    ylabel: "Voltage (V)",
                });
                plot.setData(sweep, Object.entries(voltages).map(
                    ([name, values]) => ({ name, values })
                ));
                this.plots.push(plot);
            }

            if (Object.keys(currents).length > 0) {
                const plot = new SimPlot(container, {
                    xlabel: sweepName,
                    ylabel: "Current (A)",
                });
                plot.setData(sweep, Object.entries(currents).map(
                    ([name, values]) => ({ name, values })
                ));
                this.plots.push(plot);
            }
        }
    },
    transim: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.plots = [];
        }

        update(msgData) {
            this.plots.forEach(p => p.destroy());
            this.plots = [];

            const container = document.createElement('div');
            container.classList.add('simplot-container');
            this.resContent.replaceChildren(container);

            const time = msgData.time;
            const voltages = msgData.voltages;
            const currents = msgData.currents;

            if (Object.keys(voltages).length > 0) {
                const plot = new SimPlot(container, {
                    xlabel: 'Time (s)',
                    ylabel: 'Voltage (V)',
                });
                plot.setData(time, Object.entries(voltages).map(
                    ([name, values]) => ({ name, values })
                ));
                this.plots.push(plot);
            }

            if (Object.keys(currents).length > 0) {
                const plot = new SimPlot(container, {
                    xlabel: 'Time (s)',
                    ylabel: 'Current (A)',
                });
                plot.setData(time, Object.entries(currents).map(
                    ([name, values]) => ({ name, values })
                ));
                this.plots.push(plot);
            }
        }
    },
    acsim: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.plots = [];
        }

        update(msgData) {
            this.plots.forEach(p => p.destroy());
            this.plots = [];

            const container = document.createElement('div');
            container.classList.add('simplot-container');
            this.resContent.replaceChildren(container);

            const freq = msgData.freq;
            const allSignals = { ...msgData.voltages, ...msgData.currents };

            if (Object.keys(allSignals).length > 0) {
                const magSeries = [];
                const phaseSeries = [];

                for (const [name, complexValues] of Object.entries(allSignals)) {
                    magSeries.push({
                        name,
                        values: complexValues.map(([re, im]) =>
                            20 * Math.log10(Math.sqrt(re * re + im * im))
                        ),
                    });
                    phaseSeries.push({
                        name,
                        values: complexValues.map(([re, im]) =>
                            Math.atan2(im, re) * 180 / Math.PI
                        ),
                    });
                }

                const magPlot = new SimPlot(container, {
                    xlabel: 'Frequency (Hz)',
                    ylabel: 'Magnitude (dB)',
                    xscale: 'log',
                });
                magPlot.setData(freq, magSeries);
                this.plots.push(magPlot);

                const phasePlot = new SimPlot(container, {
                    xlabel: 'Frequency (Hz)',
                    ylabel: 'Phase (\u00B0)',
                    xscale: 'log',
                });
                phasePlot.setData(freq, phaseSeries);
                this.plots.push(phasePlot);
            }
        }
    },
}

export class ResultViewer {
    static refreshAll = false;

    constructor(container, state) {
        this.container = container;
        container.element.innerHTML = `
            <div class="resview">
                <div class="resviewhead"><select class="viewsel"></select></div>
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
        this.viewSelector = container.element.querySelector(".viewsel");
        this.viewUpToDate = false;
        this.viewSelected = null;
        this.refreshRequestedByUser = false;
        this.viewSelector.onchange = () => this.viewSelectorOnChange();
        if (state['view']) {
            this.restoreSelectedView = state['view'];
        }
        //this.updateGlobalState();
        this.viewListInitialized = false;
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
        this.viewSelected = this.viewSelector.options[this.viewSelector.selectedIndex].value;
        this.container.setState({
            view: this.viewSelector.options[this.viewSelector.selectedIndex].value
        });
        
        this.invalidate();
        this.resetResContent();
        this.resContent.focus(); // tab focus on resContent
        this.view = null;
        this.client.requestNextView();
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
        let vs = this.viewSelector;
        let prevOptVal;
        if (vs.selectedIndex > 0) {
            prevOptVal = vs.options[vs.selectedIndex].value
        } else {
            prevOptVal = this.restoreSelectedView;
        }
        vs.innerHTML = "<option disabled selected value>--- Select result from list ---</option>";
        let selectedVal = null;
        this.client.views.forEach(view => {
            var option = document.createElement("option");
            option.innerText = view.name;
            option.value = view.name;
            vs.appendChild(option)
            if (view.name == prevOptVal) {
                option.selected = true;
                selectedVal = view.name;
            }
        });
        this.viewSelected = selectedVal;
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
