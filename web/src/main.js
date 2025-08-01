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

import { ResultViewer } from "./resultviewer.js"

var editor;
const sourceTypeSelect = document.getElementById("sourcetype");
const urlParams = new URLSearchParams(window.location.search);

// add &debug=true to show 'debug' elements
const debug = urlParams.get('debug');
if(debug) {
    Array.from(document.getElementsByClassName("debug")).forEach(function(e) {
        e.style.display = "block";
    })
}

function getSourceType() {
    return sourceTypeSelect.options[sourceTypeSelect.selectedIndex].value;
}

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

class Editor {
    constructor(container, state) {
        this.refreshTimeout = 0;
        this.container = container
        this.resizeWithContainerAutomatically = true

        this.editor = ace.edit(container.element);
        this.editor.setTheme("ace/theme/github");
        this.editor.session.setMode("ace/mode/python");
        this.editor.setOptions({
            fontFamily: "Inconsolata",
            fontSize: "12pt"
        });
        this.editor.session.on('change', this.changed.bind(this));

        editor = this;
    }

    loadSrc(src) {
        this.editor.setValue(src)
        this.editor.clearSelection()
    }

    changed(delta) {
        if(this.refreshTimeout <= 0) {
            this.handleUpdate()
        } else {
            window.clearTimeout(this.timeout)
            this.timeout = window.setTimeout(
                () => {
                    console.log('ordecRestartSession triggered from editor');
                    this.handleUpdate()
                },
                this.refreshTimeout
            );
        }
    }
}

class OrdecClient {
    constructor(layout, srctype, resultViewers) {
        this.layout = layout
        this.views = []
        this.reqPending = false
        this.srctype = srctype
        this.resultViewers = resultViewers
    }

    getAuthCookie() {
        let authCookie = '';
        document.cookie.split(';').forEach(function(el) {
            let split = el.split('=');
            if(split[0].trim() == 'ordecAuth') {
                authCookie = split.slice(1).join("=");
            }
        })
        return authCookie;
    }

    connect() {
        if (this.sock) {
            this.sock.close();
        }
        const wsUrl = new URL('/api/websocket', location.href);
        if(wsUrl.protocol=='http:') {
            wsUrl.protocol = 'ws:';
        } else {
            wsUrl.protocol = 'wss:';
        }
        this.sock = new WebSocket(wsUrl.href, []);
        this.sock.onopen = this.wsOnOpen.bind(this);
        this.sock.onmessage = this.wsOnMessage.bind(this);
        this.sock.onclose = this.wsOnClose.bind(this);
        this.reqPending = false;
    }

    wsOnMessage(messageEvent) {
        const msg = JSON.parse(messageEvent.data);
        //console.log(msg)
        if ((msg['msg'] == 'views') || (msg['msg'] == 'exception')) {
            if (msg['msg'] == 'exception') {
                this.exception = msg['exception']
                setStatus('exception')
            } else {
                this.exception = undefined
                this.views = msg['views']
            }
            this.resultViewers.forEach(function(rv) {
                rv.updateGlobalState()
            })
            this.requestNextView()
        } else if (msg['msg'] == 'view') {
            this.nextView.updateView(msg);
            this.reqPending = false;
            this.requestNextView();
        }
    };

    wsOnClose(closeEvent) {
        if (!this.exception) {
            this.exception = "Websocket disconnected.";
            setStatus('disconnected')
        }
        this.resultViewers.forEach(function(rv) {
            rv.updateGlobalState()
        })
    };

    wsOnOpen(event) {
        setStatus('busy')
        this.sock.send(JSON.stringify({
            'msg': 'source',
            'srctype': this.srctype,
            'src': editor.editor.getValue(),
            'auth': this.getAuthCookie(),
        }))
    }

    requestNextView() {
        if (this.reqPending) {
            return;
        }

        this.nextView = undefined;
        this.resultViewers.some((rv) => {
            if (!rv.viewLoaded && rv.viewRequested) {
                this.nextView = rv;
                return true; // = "break;" in some()
            }
        })

        if (this.nextView) {
            //console.log('next view', nextView.viewRequested)
            this.sock.send(JSON.stringify({
                'msg': 'getview',
                'view': this.nextView.viewRequested,
            }))
            this.reqPending = true;
        } else {
            if (!this.exception) {
                setStatus('ready')
            }
        }
    }
}

async function getInitData() {
    var paramExample = urlParams.get('example');
    if (!paramExample) {
        paramExample = 'blank';
    }

    const response = await fetch("/api/example?name=" + paramExample); // TODO: Potential XSS?!
    if (!response.ok) {
        throw new Error(`Response status: ${response.status}`);
    }
    return await response.json();
}

const initData = await getInitData()
initData.uistate.header = {"popout": false};

const layout = new GoldenLayout(document.getElementById("workspace"));
layout.layoutConfig.settings.showPopoutIcon = false;
layout.resizeWithContainerAutomatically = true;
layout.registerComponent('editor', Editor);
layout.registerComponent('result', ResultViewer);
layout.loadLayout(initData.uistate);

function getResultViewers() {
    var ret = [];
    layout.root.getAllContentItems().forEach(function(e) {
        if (!e.isComponent) return;
        if (e.componentName != 'result') return;
        ret.push(e.component);
    });
    return ret;
}

sourceTypeSelect.value = initData.srctype;

document.getElementById("newresview").onclick = function() {
    layout.addComponent('result', undefined, 'Result View');
};

document.getElementById("savejson").onclick = function() {
    const uistate = LayoutConfig.fromResolved(layout.saveLayout());

    const dataStr = "data:application/json;charset=utf-8,"
        + encodeURIComponent(JSON.stringify(uistate, null, 2));
    const dlAnchorElem = document.getElementById('downloadAnchorElem');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("target", "_blank");
    dlAnchorElem.click();
}

window.ordecClient = new OrdecClient(layout, getSourceType(), getResultViewers())

editor.handleUpdate = window.ordecClient.connect.bind(window.ordecClient);
editor.loadSrc(initData.src);
// 1st request, caused by loadSrc, is with refreshTimeout = 0.
editor.refreshTimeout = 500; 

sourceTypeSelect.onchange = function() {
    window.ordecClient.srctype = getSourceType()
    window.ordecClient.connect()
};
layout.addEventListener('stateChanged', () => layout.resultViewers = getResultViewers())
