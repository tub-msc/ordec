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
import { OrdecClient } from './client.js'

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

        window.ordecClient.editor = this
    }

    loadSrc(src) {
        this.editor.setValue(src)
        this.editor.clearSelection()
    }

    changed(delta) {
        if(this.refreshTimeout <= 0) {
            window.ordecClient.connect()
        } else {
            window.clearTimeout(this.timeout)
            this.timeout = window.setTimeout(
                () => {
                    console.log('ordecRestartSession triggered from editor');
                    window.ordecClient.connect()
                },
                this.refreshTimeout
            );
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

sourceTypeSelect.value = initData.srctype;

window.ordecClient = new OrdecClient(
    getSourceType(),
    [],
    setStatus,
)

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


layout.addEventListener('stateChanged', () => window.ordecClient.resultViewers = getResultViewers())

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

sourceTypeSelect.onchange = function() {
    window.ordecClient.srctype = getSourceType()
    window.ordecClient.connect()
};

window.ordecClient.editor.loadSrc(initData.src);
// 1st request, caused by loadSrc, is with refreshTimeout = 0.
window.ordecClient.editor.refreshTimeout = 500; 
