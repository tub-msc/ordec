// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// To be improved. Consider the constructor-only classes stubs for future functions.

import * as d3 from "d3";

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

            this.resContent.innerHTML = '';
            this.resContent.append(svg.node());
        }
    },
    dcsim: class {
        constructor(resContent) {
            this.resContent = resContent;
        }

        update(msgData) {
            this.resContent.innerHTML = '';
            var table = document.createElement('table');
            table.classList.add('dc_table')
            this.resContent.appendChild(table)
            table.innerHTML = '<tr><th>Net</th><th>Voltage</th></tr>'
            msgData.dc_voltages.forEach(function (row) {
                var tr = document.createElement('tr')
                table.appendChild(tr)
                tr.innerHTML = '<td>'+row[0]+'</td><td>'+row[1]+'</td>'
            })

            this.resContent.appendChild(document.createElement('br'));

            var table = document.createElement('table');
            table.classList.add('dc_table')
            this.resContent.appendChild(table)
            table.innerHTML = '<tr><th>Branch</th><th>Current</th></tr>'
            msgData.dc_currents.forEach(function (row) {
                var tr = document.createElement('tr')
                table.appendChild(tr)
                tr.innerHTML = '<td>'+row[0]+'</td><td>'+row[1] + '</td>'
            })
        }
    }
}

export class ResultViewer {
    constructor(container, state) {
        this.container = container
        container.element.innerHTML = '<div class="resview"><div class="resviewhead"><select class="viewsel"></select></div><div class="rescontent">result will be shown here</div><div class="resexception"></div></div>';
        this.resizeWithContainerAutomatically = true
        this.resContent = container.element.getElementsByClassName("rescontent")[0];
        this.resException = container.element.getElementsByClassName("resexception")[0];
        this.viewSel = container.element.getElementsByClassName("viewsel")[0];
        this.viewLoaded = false;

        this.viewRequested = undefined;
        this.viewSel.onchange = this.viewSelOnChange.bind(this);
        if (state['view']) {
            this.restoreSelectedView = state['view']
        }
        this.updateGlobalState()
    }

    viewSelOnChange() {
        this.viewRequested = this.viewSel.options[this.viewSel.selectedIndex].value;
        this.container.setState({
            'view': this.viewSel.options[this.viewSel.selectedIndex].value
        });
        
        this.invalidate();
        this.resContent.innerHTML = "";
        this.view = null;
        if (!window.ordecClient.exception) {
            window.ordecClient.requestNextView();
        }
    }

    invalidate() {
        this.viewLoaded = false;
    }

    updateGlobalState() {
        this.invalidate();
        this.updateViewList();
        this.updateExceptionState();
    }

    updateViewList() {
        var vs = this.viewSel
        var prevOptVal;
        if (vs.selectedIndex > 0) {
            prevOptVal = vs.options[vs.selectedIndex].value
        } else {
            prevOptVal = this.restoreSelectedView;
        }
        vs.innerHTML = "<option disabled selected value>--- Select result from list ---</option>";
        window.ordecClient.views.forEach(function(view) {
            var option = document.createElement("option")
            option.innerText = view
            option.value = view
            vs.appendChild(option)
            if (view == prevOptVal) {
                option.selected = true;
            }
        })
        this.viewRequested = prevOptVal
    }

    updateExceptionState() {
        if (window.ordecClient.exception) {
            this.resException.style.display = 'block';
            this.resContent.style.display = 'none';

            var pre = document.createElement("pre");
            pre.innerText = window.ordecClient.exception;
            pre.classList.add('exception')
            this.resException.innerHTML = '';
            this.resException.appendChild(pre);
            
        } else {
            this.resException.style.display = 'none';
            this.resContent.style.display = 'block';
        }
    }

    updateView(msg) {
        this.resContent.innerHTML = "";
        this.viewLoaded = true;
    
        const viewClass = viewClassOf[msg.type]
        if(!viewClass) {
            var pre = document.createElement("pre");
            pre.innerText = 'no handler found for type '+msg.type;
            this.resContent.appendChild(pre);
        } else if(this.view instanceof viewClass) {
            this.view.update(msg.data);
        } else {
            this.view = new viewClass(this.resContent);
            this.view.update(msg.data);
        } 
    }
}
