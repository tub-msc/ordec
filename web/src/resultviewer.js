// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// To be improved. Consider the constructor-only classes stubs for future functions.

const viewClassOf = {
    html: class {
        constructor(resContent, msgData) {
            this.resContent = resContent;
            this.resContent.innerHTML = msgData;
        }
    },
    dcsim: class {
        constructor(resContent, msgData) {
            this.resContent = resContent;

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
        container.element.innerHTML = '<div class="resview"><div class="resviewhead"><select class="viewsel"></select></div><div class="rescontent">result will be shown here</div></div>';
        this.resizeWithContainerAutomatically = true
        this.resContent = container.element.getElementsByClassName("rescontent")[0];
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
        if (!window.ordecClient.exception) {
            this.clear()
            window.ordecClient.requestNextView()
        }
    }

    clear() {
        this.resContent.innerHTML = "";
        this.viewLoaded = false;
    }

    updateGlobalState() {
        this.clear()
        if (window.ordecClient.exception) {
            var pre = document.createElement("pre");
            pre.innerText = window.ordecClient.exception;
            pre.classList.add('exception')
            this.resContent.appendChild(pre);
            this.viewLoaded = true;
        }
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

    updateView(msg) {
        this.viewLoaded = true;

        if (msg.exception) {
            var pre = document.createElement("pre");
            pre.innerText = msg['exception'];
            pre.classList.add('exception')
            this.resContent.appendChild(pre);
        } else {
            const viewClass = viewClassOf[msg.type]
            if(viewClass) {
                new viewClass(this.resContent, msg.data)    
            } else  {
                var pre = document.createElement("pre");
                pre.innerText = 'no handler found for type '+msg.type;
                this.resContent.appendChild(pre);
            }
        }
    }
}
