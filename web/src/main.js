// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import './style.css'
import './ace-ord-style.css'

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

import { OrdMode } from "./ace-ord-mode.js";

import { authenticateLocalQuery } from './auth.js';

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
const queryLocal = urlParams.get('local');
const queryHmac = urlParams.get('hmac');

function setEditorMode(editor, sourceType) {
    if (sourceType === "ord") {
        editor.session.setMode(new OrdMode());
    } else {
        editor.session.setMode("ace/mode/python");
    }
}

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

function unloadMsg() {
    return "Unsaved changes are lost when leaving. Do you want to leave the site?";
}

class Editor {
    constructor(container, state) {
        this.refreshTimeout = 500;
        this.container = container;
        this.resizeWithContainerAutomatically = true;

        this.editor = ace.edit(container.element);
        this.editor.setTheme("ace/theme/github");
        setEditorMode(this.editor, getSourceType());
        this.editor.setOptions({
            fontFamily: "Inconsolata",
            fontSize: "12pt"
        });
    }

    registerChangeHandler(client) {
        this.editor.session.on('change', (delta) => {
            // After the user has modified the example code, he must confirm
            // when he wants to close the browser window.
            window.onbeforeunload = unloadMsg;
            
            window.clearTimeout(this.timeout);
            this.timeout = window.setTimeout(() => {
                console.log('ordecClient.connect() triggered by editor change.');
                client.src = this.editor.getValue();
                client.connect();
            }, this.refreshTimeout);
        });
    }

    loadSrc(src) {
        this.editor.setValue(src);
        this.editor.clearSelection();
    }
}

async function getInitData() {
    let paramExample = urlParams.get('example');
    if (!paramExample) {
        paramExample = 'blank';
    }

    var params = new URLSearchParams();
    params.append('name', paramExample);

    const response = await fetch("/api/example?"+params);
    if (!response.ok) {
        throw new Error(`Response status: ${response.status}`);
    }
    return await response.json();
}

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

function getEditor() {
    let ret;
    layout.root.getAllContentItems().forEach(e => {
        if(e.componentName == 'editor') {
            ret = e.component;
        }
    });
    return ret;
}

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

let client;

if(queryLocal) {
    // If queryLocal is set, the web UI is used in **local mode**.
    // In this case, only a single result view is opened by default.

    // To prevent CSRF attacks, queryLocal is authenticated using the queryHmac
    // parameter.

    const local = await authenticateLocalQuery(queryLocal, queryHmac);

    if(local) {
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
                                "view": local.view,
                            }
                        }
                    ]
                }
            ]
        }; 
        uistate.header = {popout: false};

        layout.loadLayout(uistate);
        // client is initialized only once we have loaded our layout using loadLayout:
        client = new OrdecClient(getSourceType(), getResultViewers(), setStatus);
        client.localModule = local.module;
        client.connect();
    } else {
        console.error("HMAC authentication of 'local' parameter failed.");
    }
} else {
    // If localModule is null, the web UI is used in **integrated mode**.
    // In this case, the source code is entered through the web editor.
    // This editor and zero or more result views are initialized through
    // the data obtained from the server through getInitData().

    document.querySelector("#toolRefresh").style.display='none';

    const initData = await getInitData();
    initData.uistate.header = {popout: false};
    sourceTypeSelect.value = initData.srctype;
    layout.loadLayout(initData.uistate);
    
    // client is initialized only once we have loaded our layout using loadLayout:
    client = new OrdecClient(getSourceType(), getResultViewers(), setStatus);
    client.srctype = initData.srctype;
    client.src = initData.src;
    
    const editor = getEditor();
    editor.loadSrc(initData.src);

    client.connect();
     
    // Starting now, changes of editor source will trigger connect():   
    editor.registerChangeHandler(client); 
}

layout.addEventListener('stateChanged', () => {
    client.registerResultViewers(getResultViewers());
});

document.querySelector("#refresh").onclick = () => {
    client.connect();
};

sourceTypeSelect.onchange = () => {
    const sourceType = getSourceType();
    client.srctype = sourceType;

    const editor = getEditor();
    if (editor) {
        setEditorMode(editor.editor, sourceType);
    }

    console.log('ordecClient.connect() triggered by source type selector.');
    client.connect();
};

// Make the OrdecClient object easy to access for automated testing & browser-based debugging:
window.ordecClient = client;

fetch('/api/version').then(response => response.json()).then(data => {
    document.querySelector('#version').innerText = data['version'];
});
