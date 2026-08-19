// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Entry point for app.html, the in-app design workspace. The landing page
// (index.html) has its own, much lighter entry point in landing-page.js.

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
import "ace-builds/src-noconflict/ext-searchbox";

import { OrdMode } from "./ace-ord-mode.js";

import { authenticateLocalQuery, initSession, session } from './auth.js';

import { ResultViewer } from "./resultviewer.js";
import { initTheme, registerAceEditor, unregisterAceEditor } from './theme.js';
import { OrdecApp } from './app.js';
import { initCourseMode, getCourseController, suppressCloseControls } from './course.js';

initTheme();

// In hub-hosted deployments, this fetches the auth token from the backend
// (api/token); must complete before the first websocket connect.
await initSession();

// Behind JupyterHub, surface an "End session" control that stops the container
// and logs out (the hub is configured with shutdown_on_logout). The landing
// page duplicates this wiring in an inline script (web/index.html, which does
// not load this bundle); keep both in sync.
if (session.hubMode && session.hubLogoutUrl) {
    const endSession = document.querySelector("#hubEndSession");
    endSession.href = session.hubLogoutUrl;
    endSession.hidden = false;
    endSession.addEventListener("click", (e) => {
        if (!window.confirm("End this session? Your container will be stopped "
                + "and unsaved work will be lost.")) {
            e.preventDefault();
        }
    });
}

const sourceTypeSelect = document.querySelector("#sourcetype");
const urlParams = new URLSearchParams(window.location.hash.substring(1));

// Reload page when URL hash changes (e.g., example=, debug=) so parameters take effect
window.addEventListener('hashchange', () => {
    window.location.reload();
});

// add &debug=true to show 'debug' elements
const debug = Boolean(urlParams.get('debug'));
if(debug) {
    document.body.classList.add('show-debug');
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

// the course= URL parameter activates course mode (see course.js).
const queryCourse = urlParams.get('course');

function getSourceType() {
    return sourceTypeSelect.options[sourceTypeSelect.selectedIndex].value;
}

function setStatus(status) {
    let divStatus = document.querySelector("#status");
    divStatus.innerText = status;
    divStatus.className = 'item status-' + status;
}

function unloadMsg() {
    return "Unsaved changes are lost when leaving. Do you want to leave the site?";
}

class Editor {
    constructor(container, state) {
        this.refreshTimeout = 500;
        this.container = container;

        this.editor = ace.edit(container.element);
        registerAceEditor(this.editor);
        this.updateMode();
        // Font size comes from the shared --font-size-code token, which also
        // sizes the preformatted/code text in reports.
        this.editor.setOptions({
            fontFamily: "Inconsolata",
            fontSize: getComputedStyle(document.documentElement)
                .getPropertyValue('--font-size-code').trim() || "11.5pt"
        });

        // Teardown when GoldenLayout releases the component, e.g. when
        // loadLayout() rebuilds the panels on a lesson switch (course.js).
        // Clearing the timeout is not just hygiene: a pending debounce
        // would fire after activateLesson() has installed the new lesson's
        // source and overwrite client.src with the old lesson's text.
        container.addEventListener('beforeComponentRelease', () => {
            window.clearTimeout(this.timeout);
            unregisterAceEditor(this.editor);
            this.editor.destroy();
        });

        // The source editor is movable but not closable in every mode (see
        // suppressCloseControls).
        suppressCloseControls(container);

        // In course mode, register with the controller so it can read/replace
        // the editor source on lesson switches. The navigator toolbar lives in
        // the Course result viewer's header, not here (see course.js).
        getCourseController()?.setEditor(this);
    }

    registerChangeHandler(client) {
        this.editor.session.on('change', (delta) => {
            const courseController = getCourseController();
            if (courseController) {
                // Course mode: edits are autosaved to localStorage, no
                // confirmation on unload needed.
                courseController.autosaveSrc(this.editor.getValue());
            } else {
                // After the user has modified the example code, he must
                // confirm when he wants to close the browser window.
                window.onbeforeunload = unloadMsg;
            }

            window.clearTimeout(this.timeout);
            if (client.autoRefreshEnabled) {
                this.timeout = window.setTimeout(() => {
                    console.log('ordecClient.connect() triggered by editor change.');
                    client.src = this.editor.getValue();
                    client.connect();
                }, this.refreshTimeout);
            }
        });
    }

    loadSrc(src) {
        this.editor.setValue(src);
        this.editor.clearSelection();
    }

    updateMode() {
        if (getSourceType() == "ord") {
            this.editor.session.setMode(new OrdMode());
        } else {
            this.editor.session.setMode("ace/mode/python");
        }
    }
}

async function getInitData() {
    let paramExample = urlParams.get('example');
    if (!paramExample) {
        paramExample = 'blank';
    }

    var params = new URLSearchParams();
    params.append('name', paramExample);

    const response = await fetch("api/example?"+params);
    if (!response.ok) {
        throw new Error(`Response status: ${response.status}`);
    }
    return await response.json();
}

function popRestoreData() {
    // Source stashed by the session-lost overlay (client.js) right before
    // a reload that respawns a hub-hosted instance.
    const raw = window.sessionStorage.getItem('ordecRestore');
    if (!raw) {
        return null;
    }
    window.sessionStorage.removeItem('ordecRestore');
    try {
        return JSON.parse(raw);
    } catch (e) {
        return null;
    }
}

// Page overlay shown when a hub-hosted instance is culled and can no longer be
// reconnected to (OrdecClient calls this via its onSessionLost callback). The
// restart button stashes the source for popRestoreData to pick up after the
// reload respawns the instance through the hub.
function showSessionLost() {
    if (document.querySelector('#sessionlost')) {
        return;
    }
    const overlay = document.createElement('div');
    overlay.id = 'sessionlost';
    const box = document.createElement('div');
    box.className = 'sessionlost-box';
    const text = document.createElement('p');
    text.textContent = 'Your session was stopped (e.g. after being idle '
        + 'for a while). Restarting starts a fresh session and restores '
        + 'your editor content.';
    const button = document.createElement('button');
    button.className = 'sessionlost-button';
    button.textContent = 'Restart session';
    button.onclick = () => {
        // Integrated-mode source only lives in this page; carry it across the
        // reload. (Course mode autosaves to localStorage independently of this.)
        try {
            window.sessionStorage.setItem('ordecRestore', JSON.stringify({
                src: app.client.src,
                srctype: app.client.srctype,
            }));
        } catch (e) { /* storage full/blocked: reload without restore */ }
        window.onbeforeunload = null;
        window.location.reload();
    };
    box.appendChild(text);
    box.appendChild(button);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
}

const layout = new GoldenLayout(document.querySelector("#workspace"));
layout.layoutConfig.settings.showPopoutIcon = false;
layout.resizeWithContainerAutomatically = true;
layout.registerComponent('editor', Editor);
layout.registerComponent('result', ResultViewer);

// Owns the frontend's mutable runtime state (event bus, layout, client).
const app = new OrdecApp({ layout, setStatus, onSessionLost: showSessionLost });

// The GoldenLayout content items that are components of the given name (e.g.
// 'result' or 'editor'). The layout tree is the source of truth for which
// viewers/editors currently exist, so all lookups below derive from it live.
function componentItems(name) {
    return layout.root.getAllContentItems()
        .filter(item => item.isComponent && item.componentName === name);
}

function getResultViewers() {
    return componentItems('result').map(item => item.component);
}

function findResultViewerByView(viewName) {
    return componentItems('result')
        .find(item => item.component.viewSelected === viewName);
}

function findResultViewerByWireHash(wireHash) {
    return componentItems('result')
        .find(item => item.component.wireHash === wireHash);
}

function resolveExistingViewer(viewName, wireHash) {
    // Name match first; otherwise match by subgraph wire hash: the same
    // subgraph is often reachable under several names (e.g. X().layout vs
    // X().lvs.ref_layout), and opening it twice should be avoided. The hash
    // comes with the requesting view's data (e.g. layout_wire_hash in report
    // webdata), so the lookup is purely local.
    return findResultViewerByView(viewName)
        || (wireHash ? findResultViewerByWireHash(wireHash) : null);
}

function getEditor() {
    return componentItems('editor')[0]?.component;
}

document.querySelector("#newresview").onclick = () => {
    // The new viewer pops open the first dropdown of its view selector
    // (see updateViewList), riding on this click's user activation.
    ResultViewer.autoOpenPending = true;
    // In course mode, never open the new view as a tab on top of the Course
    // panel or the source editor (GoldenLayout's default placement picks the
    // first stack, which is the Course panel's): stack it onto an existing
    // result viewer instead, or open a new stack at the root.
    if (getCourseController()) {
        const config = {
            type: 'component',
            componentName: 'result',
            title: 'Result View',
        };
        for (const item of layout.root.getAllContentItems()) {
            if (item.isComponent && item.componentName === 'result'
                && item.component && !item.component.courseMode) {
                item.parent.addItem(config);
                return;
            }
        }
        layout.root.contentItems[0].addItem(config);
        return;
    }
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

// Local mode: only a single result view is opened by default. To prevent CSRF
// attacks, queryLocal is authenticated using the queryHmac parameter. Returns
// null (no client) if authentication fails.
async function initLocalMode() {
    const local = await authenticateLocalQuery(queryLocal, queryHmac);
    if (!local) {
        console.error("HMAC authentication of 'local' parameter failed.");
        return null;
    }

    document.querySelector("#toolSourcetype").style.display = 'none';

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
    const client = app.startClient(getSourceType(), getResultViewers());
    client.localModule = local.module;
    client.connect();
    return client;
}

// Course mode: the CourseController loads sources and per-lesson layouts from
// the /api/course endpoint (combined with progress saved in localStorage) and
// rebuilds editor + result views on each lesson switch.
async function startCourseMode() {
    document.querySelector("#toolSourcetype").style.display = 'none';

    const client = app.startClient(getSourceType(), []);

    const controller = await initCourseMode(queryCourse, client, layout, {
        getResultViewers,
        saveUistate: () => LayoutConfig.fromResolved(layout.saveLayout()),
        setSourceType: (srctype) => { sourceTypeSelect.value = srctype; },
        // debug=true in the URL fragment unlocks all lessons at once.
        debug,
    });

    controller.activateLesson(controller.currentLesson, { save: false });

    // Make the controller easy to access for automated testing & debugging:
    window.courseController = controller;
    return client;
}

// Integrated mode: the source code is entered through the web editor. This
// editor and zero or more result views are initialized through the data
// obtained from the server through getInitData().
async function initIntegratedMode() {
    const initData = await getInitData();
    const restoreData = popRestoreData();
    if (restoreData) {
        initData.src = restoreData.src;
        initData.srctype = restoreData.srctype;
    }
    initData.uistate.header = {popout: false};
    sourceTypeSelect.value = initData.srctype;
    layout.loadLayout(initData.uistate);

    // client is initialized only once we have loaded our layout using loadLayout:
    const client = app.startClient(getSourceType(), getResultViewers());
    client.srctype = initData.srctype;
    client.src = initData.src;

    const editor = getEditor();
    editor.loadSrc(initData.src);

    client.connect();

    // Starting now, changes of editor source will trigger connect():
    editor.registerChangeHandler(client);
    return client;
}

if (queryLocal) {
    await initLocalMode();
} else if (queryCourse) {
    await startCourseMode();
} else {
    await initIntegratedMode();
}

layout.addEventListener('stateChanged', () => {
    app.client.registerResultViewers(getResultViewers());
    getCourseController()?.uistateChanged();
});

function refresh() {
    if (!app.client.localModule) {
        const editor = getEditor();
        if (editor) {
            app.client.src = editor.editor.getValue();
        }
    }
    app.client.connect();
}

const refreshBtn = document.querySelector("#refresh");
refreshBtn.onmousedown = (e) => e.preventDefault();
refreshBtn.onclick = refresh;

document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'm') {
        e.preventDefault();
        refresh();
    }
});

sourceTypeSelect.onchange = () => {
    const sourceType = getSourceType();
    app.client.srctype = sourceType;

    getEditor().updateMode();

    console.log('ordecClient.connect() triggered by source type selector.');
    app.client.connect();
};

const autoRefreshToggle = document.querySelector("#autoRefreshToggle");
autoRefreshToggle.onmousedown = (e) => e.preventDefault();
autoRefreshToggle.onclick = () => {
    app.client.autoRefreshEnabled = !app.client.autoRefreshEnabled;
    autoRefreshToggle.classList.toggle('active', app.client.autoRefreshEnabled);
    autoRefreshToggle.textContent = app.client.autoRefreshEnabled ? 'Auto-refresh: on' : 'Auto-refresh: off';
};

// Make the OrdecApp object easy to access for automated testing & browser-based debugging:
window.ordecApp = app;

// Opens itemConfig beside sourceStack by replacing sourceStack in its parent
// (a column or the ground) with a new row [sourceStack, itemConfig]. When the
// parent is a row, the caller inserts into it directly instead.
function wrapStackInRow(sourceStack, itemConfig) {
    const stackParent = sourceStack.parent;
    const stackIndex = stackParent.contentItems.indexOf(sourceStack);
    const rowConfig = {
        type: 'row',
        content: [itemConfig]
    };
    if (stackParent.isColumn) {
        // Insert the wrapper row before removing sourceStack: removing first
        // can leave the column with a single child, which GoldenLayout
        // condenses away (the column is replaced by that child and
        // destroyed), losing the subsequent addItem and the removed stack.
        stackParent.addItem(rowConfig, stackIndex);
        const newRow = stackParent.contentItems[stackIndex];
        stackParent.removeChild(sourceStack, true);
        newRow.addChild(sourceStack, 0);
    } else {
        // Ground item: sourceStack is the layout root. A ground holds only a
        // single child, so here the root must be removed first (addItem on a
        // non-empty ground delegates into the existing root instead).
        stackParent.removeChild(sourceStack, true);
        stackParent.addItem(rowConfig, stackIndex);
        const newRow = stackParent.contentItems[stackIndex];
        newRow.addChild(sourceStack, 0);
    }
}

// Opens result viewers for componentConfigs (GoldenLayout 'result' component
// configs) beside the stack holding sourceContainer: as the next sibling if
// that stack sits in a row, otherwise by wrapping the stack in a new row (see
// wrapStackInRow). A single config is placed on its own; several are grouped in
// a column. With no source stack (e.g. the source is the ground/root), the
// viewers open as new top-level stacks instead.
function openViewsBesideSource(sourceContainer, componentConfigs) {
    if (componentConfigs.length === 0) {
        return;
    }

    const sourceStack = sourceContainer?.parent?.parent;

    if (!sourceStack?.isStack) {
        componentConfigs.forEach(config => {
            layout.addComponent('result', config.componentState, config.title);
        });
        return;
    }

    const itemToAdd = componentConfigs.length === 1
        ? componentConfigs[0]
        : { type: 'column', content: componentConfigs };

    const stackParent = sourceStack.parent;

    if (stackParent.isRow) {
        const index = stackParent.contentItems.indexOf(sourceStack) + 1;
        stackParent.addItem(itemToAdd, index);
    } else {
        wrapStackInRow(sourceStack, itemToAdd);
    }
}

function openOrActivateView(data) {
    const view = data.view;

    if (view) {
        const existing = resolveExistingViewer(view, data.wireHash);
        if (existing) {
            existing.focus();
            return;
        }
    }

    const componentState = view ? { view, directView: true } : undefined;
    const title = view || 'Result View';

    const componentConfig = {
        type: 'component',
        componentName: 'result',
        componentState,
        title,
    };

    openViewsBesideSource(data.sourceContainer, [componentConfig]);
}

app.eventBus.on('layout:request-open', openOrActivateView);
app.eventBus.on('schematic:request-open', openOrActivateView);

// Click-to-source: jump the editor to a clicked instance's definition line.
// In local mode the user edits files externally, so we just log.
app.eventBus.on('editor:goto-source', (data) => {
    const editorComponent = getEditor();
    if (editorComponent && data.file === '<webeditor>' && data.line) {
        // ORD columns are 1-based; Ace's gotoLine expects a 0-based column.
        const aceColumn = data.column ? data.column - 1 : 0;
        editorComponent.editor.gotoLine(data.line, aceColumn, true);
        editorComponent.editor.focus();
    } else if (data.line) {
        console.info(`Instance defined at ${data.file}:${data.line}`);
    }
});

// Build errors mark the failing line in the editor with a red gutter
// annotation: the syntax error position if there is one, otherwise the
// deepest traceback frame in the editor source. Cleared again by the
// null emitted on the next successful build (client.js). Operational
// errors (auth, protocol) carry no position and just clear the annotation.
app.eventBus.on('editor:build-exception', (exc) => {
    const editorComponent = getEditor();
    if (!editorComponent) {
        return;
    }
    let row = null, column = 0;
    if (exc) {
        if (exc.pos && exc.pos.filename === '<webeditor>') {
            row = exc.pos.lineno - 1;
            column = (exc.pos.col || 1) - 1;
        } else {
            const frame = (exc.frames || []).findLast(
                f => f.filename === '<webeditor>');
            if (frame) {
                row = frame.lineno - 1;
            }
        }
    }
    editorComponent.editor.session.setAnnotations((row === null) ? [] : [{
        row,
        column,
        type: 'error',
        text: exc.message ? `${exc.etype}: ${exc.message}` : exc.etype,
    }]);
});

app.eventBus.on('lvs:request-open-views', (data) => {
    const { layoutView, schemView, layoutWireHash, schemWireHash, sourceContainer } = data;

    const layoutExisting = layoutView
        ? resolveExistingViewer(layoutView, layoutWireHash) : null;
    const schemExisting = schemView
        ? resolveExistingViewer(schemView, schemWireHash) : null;

    const columnContent = [];

    if (layoutView) {
        if (layoutExisting) {
            layoutExisting.focus();
        } else {
            columnContent.push({
                type: 'component',
                componentName: 'result',
                componentState: { view: layoutView, directView: true },
                title: layoutView,
            });
        }
    }

    if (schemView) {
        if (schemExisting) {
            schemExisting.focus();
        } else {
            columnContent.push({
                type: 'component',
                componentName: 'result',
                componentState: { view: schemView, directView: true },
                title: schemView,
            });
        }
    }

    openViewsBesideSource(sourceContainer, columnContent);
});

document.querySelector("#examples").onclick = () => {
    // Relative so it works under a URL path prefix (JupyterHub).
    if (window.onbeforeunload) {
        window.open('index.html', '_blank');
    } else {
        window.location.href = 'index.html';
    }
};

fetch('api/version').then(response => response.json()).then(data => {
    document.querySelector('#version').innerText = data['version'];
    // Point the Docs toolbar link at the documentation matching the
    // installed version.
    document.querySelector('#docs').href = data['docs_url'];
});

// Schematic CSS is served from the backend (SchematicRenderer.css in render.py)
// rather than bundled as a frontend asset. This keeps a single source of truth
// for the styles used by both standalone SVG export and the web UI, avoids
// duplicating the CSS into every inline SVG in the DOM, and reduces data
// transferred when multiple schematics are open.
fetch('api/schematic.css').then(response => response.text()).then(css => {
    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
});
