// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import './style.css'
import {
    GoldenLayout,
    LayoutConfig
} from 'golden-layout'
import "golden-layout/dist/css/goldenlayout-base.css"
import "golden-layout/dist/css/themes/goldenlayout-light-theme.css"

import 'ace-builds/src-noconflict/ace'
import "ace-builds/src-noconflict/mode-python";
import "ace-builds/src-noconflict/theme-github";
import "ace-builds/src-noconflict/ext-language_tools";

const refreshTimeout = 500;

var globalException = undefined;
var globalViews = [];
var ordecSock;
var nextView = undefined;
var reqPending = false;
var editor;
const sourceTypeSelect = document.getElementById("sourcetype");

function setStatus(status) {
    var div_status = document.getElementById("status");
    div_status.innerText = status;
    if (status == 'busy') {
        div_status.style.backgroundColor = '#ffff44';
    } else if (status == 'ready') {
        div_status.style.backgroundColor = '#44ff44';
    } else if (status == 'exception') {
        div_status.style.backgroundColor = '#ff4444';
    } else if (status == 'disconnected') {
        div_status.style.backgroundColor = '#ff4444';
    } else {
        div_status.style.backgroundColor = '#ffffff';
    }
}

class ResultViewer {
    constructor(container, state) {
        this.container = container
        this.rootElement = container.element
        this.rootElement.innerHTML =
            '<div class="resview"><div class="resviewhead"><select class="viewsel"></select></div><div class="rescontent">result will be shown here</div></div>';
        this.resizeWithContainerAutomatically = true
        this.resContent = this.rootElement.getElementsByClassName("rescontent")[0];
        this.viewSel = this.rootElement.getElementsByClassName("viewsel")[0];
        this.viewLoaded = false;

        this.viewRequested = undefined
        const this2 = this;
        this.viewSel.onchange = function() {
            this2.viewRequested = this2.viewSel.options[this2.viewSel.selectedIndex].value;
            const s = {
                'view': this2.viewSel.options[this2.viewSel.selectedIndex].value
            };
            this2.container.setState(s);
            if (!globalException) {
                this2.clear()
                requestNextView()
            }
        };
        if (state['view']) {
            this.restoreSelectedView = state['view']
        }
        this.updateGlobalState()


        this.container.on('resize',() => this.resize())
    }

    clear() {
        this.resContent.innerHTML = "";
        this.viewLoaded = false;
    }

    updateGlobalState() {
        this.clear()
        if (globalException) {
            var pre = document.createElement("pre");
            pre.innerText = globalException;
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
        globalViews.forEach(function(view) {
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

    resize() {
        // console.log('component.resize');
        // if(this.chart) {
        //     this.chart.resize()
        // }
    }

    updateView(msg) {
        this.viewLoaded = true;

        if (msg['dc_voltages']) {
            var table = document.createElement('table');
            table.classList.add('dc_table')
            this.resContent.appendChild(table)
            table.innerHTML = '<tr><th>Net</th><th>Voltage</th></tr>'
            msg['dc_voltages'].forEach(function (row) {
                var tr = document.createElement('tr')
                table.appendChild(tr)
                tr.innerHTML = '<td>'+row[0]+'</td><td>'+row[1]+'</td>'
            })

            this.resContent.appendChild(document.createElement('br'));

            var table = document.createElement('table');
            table.classList.add('dc_table')
            this.resContent.appendChild(table)
            table.innerHTML = '<tr><th>Branch</th><th>Current</th></tr>'
            msg['dc_currents'].forEach(function (row) {
                var tr = document.createElement('tr')
                table.appendChild(tr)
                tr.innerHTML = '<td>'+row[0]+'</td><td>'+row[1] + '</td>'
            })

        } else if (msg['html']) {
            /*
            var img = document.createElement("img");
            img.src = msg['img'];
            img.classList.add("resimg");
            this.resContent.appendChild(img);
            */
            this.resContent.innerHTML = msg['html'];
        } else if (msg['exception']) {
            var pre = document.createElement("pre");
            pre.innerText = msg['exception'];
            pre.classList.add('exception')
            this.resContent.appendChild(pre);
        } else {
            var pre = document.createElement("pre");
            pre.innerText = msg['tree'];
            this.resContent.appendChild(pre);
        }
    }
}

class Editor {
    constructor(container, state) {
        this.container = container
        this.rootElement = container.element
        //this.rootElement.innerHTML = "<div></div>"
        this.resizeWithContainerAutomatically = true

        this.editor = ace.edit(this.rootElement);
        this.editor.setTheme("ace/theme/github");
        this.editor.session.setMode("ace/mode/python");
        this.editor.setOptions({
            fontFamily: "Inconsolata",
            fontSize: "12pt"
        });
        this.editor.session.on('change', (e) => this.changed(e));

        if (state['sourceType']) {
            sourceTypeSelect.value = state['sourceType']
        }

        editor = this;
        sourceTypeSelect.onchange = function() {
            editor.settled();
        };
    }

    loadSrc(src) {
        this.editor.setValue(src)
        this.editor.clearSelection()
    }

    changed(delta) {
        window.clearTimeout(this.timeout)
        this.timeout = window.setTimeout(() => this.settled(), refreshTimeout);
    }

    settled() {
        console.log('ordecRestartSession triggered from editor');
        ordecRestartSession();

        // The source text is no longer saved in the JSON state. Instead,
        // store it separately in ordec/lib/examples/.
        this.container.setState({
            // source: this.editor.getValue(),
            sourceType: sourceTypeSelect.options[sourceTypeSelect.selectedIndex].value,
        });
    }
}

const urlParams = new URLSearchParams(window.location.search);
var paramExample = urlParams.get('example');
if (!paramExample) {
    paramExample = 'blank';
}

// add &debug=true to show 'debug' elements
var debug = urlParams.get('debug');
if(debug) {
    Array.from(document.getElementsByClassName("debug")).forEach(function(e) {
        e.style.display = "block";
    })
}

const response = await fetch("/api/example?name=" + paramExample); // TODO: Potential XSS?!
if (!response.ok) {
    throw new Error(`Response status: ${response.status}`);
}

const response_data = await response.json();

const config = response_data['uistate'];
config["header"] = {
    "popout": false
}

var myLayout = new GoldenLayout(document.getElementById("workspace"));
//var myLayout = new GoldenLayout(document.body); // this works better than the old #workspace div
window.myLayout = myLayout; // for easy access from console

myLayout.layoutConfig.settings.showPopoutIcon = false;
myLayout.resizeWithContainerAutomatically = true;
myLayout.registerComponent('editor', Editor);
//myLayout.registerComponent('example', MyComponent);
myLayout.registerComponent('result', ResultViewer);
myLayout.loadLayout(config);

editor.loadSrc(response_data['src']);

document.getElementById("newresview").onclick = function() {
    myLayout.addComponent('result', undefined, 'Result View');
};

document.getElementById("savejson").onclick = function() {
    var cfg = LayoutConfig.fromResolved(myLayout.saveLayout());

    var dataStr = "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(cfg, null, 2));
    var dlAnchorElem = document.getElementById('downloadAnchorElem');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("target", "_blank");
    dlAnchorElem.click();
}

function getSourceType() {
    return sourceTypeSelect.options[sourceTypeSelect.selectedIndex].value;
}

function getAuthCookie() {
  let authCookie = '';
  document.cookie.split(';').forEach(function(el) {
    let split = el.split('=');
    if(split[0].trim() == 'ordecAuth') {
        authCookie = split.slice(1).join("=");
    }
  })
  return authCookie;
}

function ordecRestartSession() {
    if (ordecSock) {
        ordecSock.close();
    }
    //ordecSock = new WebSocket("ws://localhost:9123/websocket", "ordecExperimental", );
    const wsUrl = new URL('/api/websocket', location.href);
    if(wsUrl.protocol=='http:') {
        wsUrl.protocol = 'ws:';
    } else {
        wsUrl.protocol = 'wss:';
    }
    console.log(wsUrl.href)
    ordecSock = new WebSocket(wsUrl.href, []);
    ordecSock.onopen = (event) => {
        setStatus('busy')
        const select_source = document.getElementById("sourcetype");
        ordecSock.send(JSON.stringify({
            'msg': 'source',
            'source_type': getSourceType(),
            'source_data': editor.editor.getValue(),
            'auth': getAuthCookie(),
        }))
    }

    ordecSock.onmessage = ordecOnMessage;
    ordecSock.onclose = ordecOnClose;
    reqPending = false;
}

function getResultViewers() {
    var ret = [];
    window.myLayout.root.getAllContentItems().forEach(function(e) {
        if (!e.isComponent) return;
        if (e.componentName != 'result') return;
        ret.push(e.component);
    });
    return ret;
}

function requestNextView() {
    if (reqPending) {
        return;
    }

    nextView = undefined;
    getResultViewers().some(function(rv) {
        if (!rv.viewLoaded && rv.viewRequested) {
            nextView = rv;
            return true; // = "break;" in some()
        }
    })

    if (nextView) {
        //console.log('next view', nextView.viewRequested)
        ordecSock.send(JSON.stringify({
            'msg': 'getview',
            'view': nextView.viewRequested,
        }))
        reqPending = true;
    } else {
        if (!globalException) {
            setStatus('ready')
        }
    }
}

function ordecOnMessage(messageEvent) {
    const msg = JSON.parse(messageEvent.data);
    //console.log(msg)
    if ((msg['msg'] == 'views') || (msg['msg'] == 'exception')) {
        if (msg['msg'] == 'exception') {
            globalException = msg['exception']
            setStatus('exception')
        } else {
            globalException = undefined
            globalViews = msg['views']
        }
        getResultViewers().forEach(function(rv) {
            rv.updateGlobalState()
        })
        requestNextView()
    } else if (msg['msg'] == 'view') {
        nextView.updateView(msg);
        reqPending = false;
        requestNextView();
    }
};

function ordecOnClose(closeEvent) {
    if (!globalException) {
        globalException = "Websocket disconnected.";
        setStatus('disconnected')
    }
    getResultViewers().forEach(function(rv) {
        rv.updateGlobalState()
    })
};
