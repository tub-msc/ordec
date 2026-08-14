// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { viewEventBus } from '../event-bus.js';

// Base class for the result-view renderers. ResultViewer constructs every view
// with the same (resContent, viewName, resultViewer, panelContainer) signature
// and drives it via update()/destroy(); resultViewer and panelContainer are part
// of that shared contract even where a given view does not use them.
export class View {
    constructor(resContent, viewName, resultViewer, panelContainer) {
        this.resContent = resContent;
        this.viewName = viewName;
        this.resultViewer = resultViewer;
        this.panelContainer = panelContainer;
        // Wire hash of the subgraph currently shown; set by each update().
        this.wireHash = null;
        // (event, handler) pairs registered via busSubscribe(), torn down
        // together by busUnsubscribeAll().
        this.busSubscriptions = [];
    }

    // A selection targeting targetView (optionally carrying a wire hash)
    // applies to this viewer when it is untargeted, when it names this view,
    // or when targetWireHash matches this viewer's shown subgraph - the same
    // subgraph is often reachable under several view names.
    selectionApplies(targetView, targetWireHash) {
        if (!targetView) return true;
        if (targetView === this.viewName) return true;
        return Boolean(targetWireHash && targetWireHash === this.wireHash);
    }

    // Subscribes to a view-event-bus event and remembers the (event, handler)
    // pair. Call busUnsubscribeAll() from destroy() to release every
    // subscription; a forgotten off() would leak the handler after the view is
    // replaced.
    busSubscribe(event, handler) {
        viewEventBus.on(event, handler);
        this.busSubscriptions.push([event, handler]);
    }

    busUnsubscribeAll() {
        for (const [event, handler] of this.busSubscriptions) {
            viewEventBus.off(event, handler);
        }
        this.busSubscriptions = [];
    }

    // Reads and clears the named pending-selection slot, returning its payload
    // only if it still applies to this viewer. Subclasses that use pending
    // slots map the payload's target fields via pendingApplies().
    takePendingSelection(field) {
        const pending = this[field];
        this[field] = null;
        return pending && this.pendingApplies(pending) ? pending : null;
    }

    // True if this view was built against a now-superseded result; also flashes
    // the refresh bar. An outdated report must not drive navigation or
    // highlights: its nids, positions and hashes may not match the regenerated
    // views.
    viewOutdated() {
        if (this.resultViewer.viewUpToDate) return false;
        this.resultViewer.flashRefreshBar();
        return true;
    }
}

// Small coordinate-readout widget shared by the spatial viewers (SvgView,
// LayoutGL) to show the pointer position over the canvas.
export class CoordinateDisplay {
    constructor({ tagName = 'span', classNames = [] } = {}) {
        this.element = document.createElement(tagName);
        this.element.classList.add('viewer-coordinates', ...classNames);
        this.clear();
    }

    clear() {
        this.element.textContent = 'x=-  y=-';
    }

    set(x, y) {
        this.element.textContent = `x=${x}  y=${y}`;
    }
}
