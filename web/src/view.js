// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

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
}
