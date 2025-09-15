// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// To be improved. Consider the constructor-only classes stubs for future functions.

import * as d3 from "d3";
import { LayoutGL } from './layout-gl.js';

let idCounter = 0;
export function generateId() {
    idCounter += 1;
    return "idgen" + idCounter;
}

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
    layout: class {
        constructor(resContent) {
            this.resContent = resContent;
            this.transform = d3.zoomIdentity;
            this.savedVisibility = new Map();
        }
        zoomed({transform}) {
            this.transform = transform;
            this.g.attr("transform", transform);
        }
        update(msgData) {

            const viewbox = msgData['viewbox'];
            const viewbox2 = [[viewbox[0], viewbox[1]], [viewbox[2], viewbox[3]]]

            const svg = d3.create("svg")
                .attr("class", "fit layout")
                .attr("viewBox", viewbox);

            this.g = svg.append("g")
                .html(msgData['inner'])

            let zoom = d3.zoom()
                .extent(viewbox2)
                .scaleExtent([0.9, 12])
                .translateExtent(viewbox2);

            svg.call(zoom.transform, this.transform);
            this.g.attr("transform", this.transform);

            svg.call(zoom.on("zoom", (x) => {
                this.zoomed(x);
                // Keep text + cross sizes constant:
                this.resContent.querySelectorAll(".rescale").forEach(elem => {
                    const s = 5e-7 / x.transform.k;
                    elem.transform.baseVal.getItem(0).setScale(s, s);
                });
            }));

            this.resContent.replaceChildren(svg.node());

            const layerInfo = msgData['layer_info'];

            let layersUl = document.createElement('ul');
            this.resContent.appendChild(layersUl);
            layersUl.classList.add('layerList');
            layerInfo.forEach(layer => {
                let li = document.createElement('li');
                layersUl.appendChild(li);
                const id = generateId();
                li.innerHTML = `
                  <input type="checkbox" id="${id}" name="${layer.nid}">
                  <label for="${id}">
                   <svg width="30px" height="15px" viewBox="0 0 2 1"><rect style="${layer.inline_css}" width="2" height="1" /></svg>
                   ${layer.path}
                  </label> 
                `;
            });
            this.checkboxes = layersUl.querySelectorAll('input');

            this.checkboxes.forEach(checkbox => {
                const layer_nid = Number(checkbox.name);
                // Set checked to true both for true and undefined value returned by get():
                checkbox.checked = (this.savedVisibility.get(layer_nid)!=false);
                checkbox.onclick = () => this.updateLayers();
            });

            this.updateLayers();
        }
        updateLayers() {
            this.checkboxes.forEach(checkbox => {
                const layer_nid = Number(checkbox.name);
                const layer_g = this.resContent.querySelector(".layer_nid"+layer_nid);
                layer_g.style.display = checkbox.checked?"inherit":"none";
                this.savedVisibility.set(layer_nid, checkbox.checked);
            });
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
    }
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
        this.updateGlobalState();
    }

    refreshOnClick() {
        this.refreshRequestedByUser = true;
        this.showRefreshOverlay('refreshing');
        window.ordecClient.requestNextView();
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
        let info = window.ordecClient.views.get(this.viewSelected);
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
        window.ordecClient.requestNextView();


    }

    invalidate() {
        this.viewUpToDate = false;
        this.refreshRequestedByUser = false;

        if(!this.viewSelected) {
            this.showRefreshOverlay(null);
        } else if(this.viewInfo().auto_refresh && !ResultViewer.refreshAll) {
            this.showRefreshOverlay("refreshing");
        } else {
            this.showRefreshOverlay("refreshable");
        }
    }

    updateGlobalState() {
        this.invalidate();
        this.updateViewList();
        this.updateGlobalExceptionState();
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
        window.ordecClient.views.forEach(view => {
            var option = document.createElement("option");
            option.innerText = view.name;
            option.value = view.name;
            vs.appendChild(option)
            if (view.name == prevOptVal) {
                option.selected = true;
            }
        });
        this.viewSelected = prevOptVal;
    }

    updateGlobalExceptionState() {
        if (window.ordecClient.exception) {
            this.showRefreshOverlay(null);
            this.showException(window.ordecClient.exception);
        } else {
            // this.resException.style.display = 'none';
            // this.resContent.style.display = 'block';
        }
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
    }

    testInfo() {
        // For automated browser testing (see test_web.py).
        return {
            html: this.resContent.innerHTML,
            width: this.resContent.offsetWidth,
            height: this.resContent.offsetHeight,
        };
    }
}
