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

import './auth.js';

import { ResultViewer } from "./resultviewer.js";
import { OrdecClient } from './client.js';

const sourceTypeSelect = document.querySelector("#sourcetype");
const urlParams = new URLSearchParams(window.location.search);

// add &debug=true to show 'debug' elements
const debug = Boolean(urlParams.get('debug'));
if(debug) {
    Array.from(document.querySelectorAll(".debug")).forEach(e => {
        e.style.display = "block";
    });
}

// Overrides auto_refresh=False behavior for test_web.py:
ResultViewer.refreshAll = Boolean(urlParams.get('refreshall'));

// the module= URL paramter is used to work on an external module rather than use the source editor.
const localModule = urlParams.get('module');
const localModuleView = urlParams.get('view');


function getSourceType() {
    return sourceTypeSelect.options[sourceTypeSelect.selectedIndex].value;
}

function setStatus(status) {
    let divStatus = document.querySelector("#status");
    divStatus.innerText = status;
    divStatus.style.backgroundColor = {
        'busy': '#ffff44',
        'ready': '#44ff44',
        'exception': '#ff4444',
        'disconnected': '#ff4444'
    }[status];
}

class Editor {
    constructor(container, state) {
        this.refreshTimeout = 0;
        this.container = container;
        this.resizeWithContainerAutomatically = true;

        this.editor = ace.edit(container.element);
        this.editor.setTheme("ace/theme/github");
        this.editor.session.setMode("ace/mode/python");
        this.editor.setOptions({
            fontFamily: "Inconsolata",
            fontSize: "12pt"
        });
        this.editor.session.on('change', (delta) => this.changed(delta));

        window.ordecClient.editor = this;
    }

    loadSrc(src) {
        this.editor.setValue(src);
        this.editor.clearSelection();
    }

    changed(delta) {
        if(this.refreshTimeout <= 0) {
            window.ordecClient.src = this.editor.getValue();
            console.log('ordecClient.connect() triggered by editor change (no timeout).');
            window.ordecClient.connect();
        } else {
            window.clearTimeout(this.timeout);
            this.timeout = window.setTimeout(() => {
                console.log('ordecClient.connect() triggered by editor change.');
                window.ordecClient.src = this.editor.getValue();
                window.ordecClient.connect();
            }, this.refreshTimeout);
        }
    }
}

async function getInitData() {
    let paramExample = urlParams.get('example');
    if (!paramExample) {
        paramExample = 'blank';
    }

    const response = await fetch("/api/example?name=" + paramExample); // TODO: Potential XSS?!
    if (!response.ok) {
        throw new Error(`Response status: ${response.status}`);
    }
    return await response.json();
}

window.ordecClient = new OrdecClient(getSourceType(), [], setStatus);

const layout = new GoldenLayout(document.querySelector("#workspace"));
layout.layoutConfig.settings.showPopoutIcon = false;
layout.resizeWithContainerAutomatically = true;
layout.registerComponent('editor', Editor);
layout.registerComponent('result', ResultViewer);

function getResultViewers() {
    let ret = [];
    layout.root.getAllContentItems().forEach(e => {
        if (!e.isComponent) return;
        if (e.componentName != 'result') return;
        ret.push(e.component);
    });
    return ret;
}

layout.addEventListener('stateChanged', () => {
    window.ordecClient.resultViewers = getResultViewers();
});

document.querySelector("#newresview").onclick = () => {
    layout.addComponent('result', undefined, 'Result View');
};

document.querySelector("#savejson").onclick = () => {
    const uistate = LayoutConfig.fromResolved(layout.saveLayout());

    const dataStr = "data:application/json;charset=utf-8,"
        + encodeURIComponent(JSON.stringify(uistate, null, 2));
    const dlAnchorElem = document.querySelector('#downloadAnchorElem');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("target", "_blank");
    dlAnchorElem.click();
};

document.querySelector("#refresh").onclick = () => {
    window.ordecClient.connect();
};

sourceTypeSelect.onchange = () => {
    window.ordecClient.srctype = getSourceType();
    console.log('ordecClient.connect() triggered by source type selector.');
    window.ordecClient.connect();
};

if(localModule) {
    // If localModule is set, the web UI is used in **local mode**.
    // In this case, only a single result view is opened by default.

    document.querySelector("#toolSourcetype").style.display='none';

    const uistate = {
        "content": [
            {
                "type": "row",
                "content": [
                    {
                        "type": "component",
                        "title": "Result View",
                        "componentName": "result",
                        "componentState": {
                            "view": localModuleView,
                        }
                    }
                ]
            }
        ]
    }; 
    uistate.header = {popout: false};

    layout.loadLayout(uistate);
    window.ordecClient.localModule = localModule;
    window.ordecClient.connect();
} else {
    // If localModule is null, the web UI is used in **integrated mode**.
    // In this case, the source code is entered through the web editor.
    // This editor and zero or more result views are initialized through
    // the data obtained from the server through getInitData().

    document.querySelector("#toolRefresh").style.display='none';

    const initData = await getInitData();
    initData.uistate.header = {popout: false};
    sourceTypeSelect.value = initData.srctype;
    window.ordecClient.srctype = initData.srctype;
    layout.loadLayout(initData.uistate);

    window.ordecClient.editor.loadSrc(initData.src);
    // 1st request, caused by loadSrc, is with refreshTimeout = 0.
    window.ordecClient.editor.refreshTimeout = 500; 
}

fetch('/api/version').then(response => response.json()).then(data => {
    document.querySelector('#version').innerText = data['version'];
});
