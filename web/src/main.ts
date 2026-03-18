// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import './style.css'
import './ace-ord-style.css'

import {
    GoldenLayout,
    LayoutConfig
} from 'golden-layout'
import "golden-layout/dist/css/goldenlayout-base.css"

import 'ace-builds/src-noconflict/ace'
import "ace-builds/src-noconflict/mode-python";
import "ace-builds/src-noconflict/theme-github";
import "ace-builds/src-noconflict/theme-github_dark";
import "ace-builds/src-noconflict/ext-language_tools";

import { OrdMode } from "./ace-ord-mode";

import { authenticateLocalQuery } from './auth';

import { ResultViewer } from "./resultviewer";
import { OrdecClient } from './client';
import { initTheme, registerAceEditor } from './theme';

declare const ace: any;

initTheme();

const sourceTypeSelect = document.querySelector("#sourcetype") as HTMLSelectElement;
const urlParams = new URLSearchParams(window.location.search);

// add &debug=true to show 'debug' elements
const debug = Boolean(urlParams.get('debug'));
if(debug) {
    Array.from(document.querySelectorAll(".debug")).forEach(e => {
        (e as HTMLElement).style.display = "block";
    });
}

// Overrides auto_refresh=False behavior for test_web.py:
ResultViewer.refreshAll = Boolean(urlParams.get('refreshall'));

// add &viewsel_flat=true to use flat <select> instead of hierarchical selector
if(Boolean(urlParams.get('viewsel_flat'))) {
    ResultViewer.useHierSelector = false;
}

// the module= URL paramter is used to work on an external module rather than use the source editor.
const queryLocal = urlParams.get('local');
const queryHmac = urlParams.get('hmac');

function getSourceType(): string {
    return sourceTypeSelect.options[sourceTypeSelect.selectedIndex].value;
}

function setStatus(status: string): void {
    let divStatus = document.querySelector("#status") as HTMLElement;
    divStatus.innerText = status;
    divStatus.style.backgroundColor = ({
        'busy': '#ffff44',
        'ready': '#44ff44',
        'exception': '#ff4444',
        'disconnected': '#ff4444'
    } as Record<string, string>)[status];
}

function unloadMsg(): string {
    return "Unsaved changes are lost when leaving. Do you want to leave the site?";
}

interface EditorContainer {
    element: HTMLElement;
}

class Editor {
    refreshTimeout: number;
    container: EditorContainer;
    resizeWithContainerAutomatically: boolean;
    editor: any;
    timeout: ReturnType<typeof setTimeout> | undefined;

    constructor(container: EditorContainer, state: Record<string, any>) {
        this.refreshTimeout = 500;
        this.container = container;
        this.resizeWithContainerAutomatically = true;

        this.editor = ace.edit(container.element);
        registerAceEditor(this.editor);
        this.updateMode();
        this.editor.setOptions({
            fontFamily: "Inconsolata",
            fontSize: "12pt"
        });
    }

    registerChangeHandler(client: OrdecClient): void {
        this.editor.session.on('change', (delta: any) => {
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

    loadSrc(src: string): void {
        this.editor.setValue(src);
        this.editor.clearSelection();
    }

    updateMode(): void {
        if (getSourceType() == "ord") {
            this.editor.session.setMode(new OrdMode());
        } else {
            this.editor.session.setMode("ace/mode/python");
        }
    }
}

async function getInitData(): Promise<any> {
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

const layout = new GoldenLayout(document.querySelector("#workspace") as HTMLElement);
(layout as any).layoutConfig.settings.showPopoutIcon = false;
layout.resizeWithContainerAutomatically = true;
layout.registerComponent('editor', Editor as any);
layout.registerComponent('result', ResultViewer as any);

function getResultViewers(): ResultViewer[] {
    let ret: ResultViewer[] = [];
    (layout as any).root.getAllContentItems().forEach((e: any) => {
        if (!e.isComponent) return;
        if (e.componentName != 'result') return;
        ret.push(e.component);
    });
    return ret;
}

function getEditor(): Editor {
    let ret!: Editor;
    (layout as any).root.getAllContentItems().forEach((e: any) => {
        if(e.componentName == 'editor') {
            ret = e.component;
        }
    });
    return ret;
}

(document.querySelector("#newresview") as HTMLElement).onclick = () => {
    layout.addComponent('result', undefined, 'Result View');
};

(document.querySelector("#savejson") as HTMLElement).onclick = () => {
    const uistate = LayoutConfig.fromResolved(layout.saveLayout());

    const dataStr = "data:application/json;charset=utf-8,"
        + encodeURIComponent(JSON.stringify(uistate, null, 2));
    const dlAnchorElem = document.querySelector('#downloadAnchorElem') as HTMLAnchorElement;
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("target", "_blank");
    dlAnchorElem.click();
};

let client: OrdecClient;

if(queryLocal) {
    // If queryLocal is set, the web UI is used in **local mode**.
    // In this case, only a single result view is opened by default.

    // To prevent CSRF attacks, queryLocal is authenticated using the queryHmac
    // parameter.

    const local = await authenticateLocalQuery(queryLocal, queryHmac!);

    if(local) {
        (document.querySelector("#toolSourcetype") as HTMLElement).style.display='none';

        const uistate: any = {
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

    (document.querySelector("#toolRefresh") as HTMLElement).style.display='none';

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

(document.querySelector("#refresh") as HTMLElement).onclick = () => {
    client.connect();
};

sourceTypeSelect.onchange = () => {
    const sourceType = getSourceType();
    client.srctype = sourceType;

    getEditor().updateMode();

    console.log('ordecClient.connect() triggered by source type selector.');
    client.connect();
};

// Make the OrdecClient object easy to access for automated testing & browser-based debugging:
(window as any).ordecClient = client;

fetch('/api/version').then(response => response.json()).then(data => {
    (document.querySelector('#version') as HTMLElement).innerText = data['version'];
});
