// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { OrdecClient } from './client.js';

// Pub/sub channel between the view layer and the app shell: views emit, the
// shell (and sibling views) react. setPending/getPending carry a selection made
// before its target view exists, applied once that view opens.
class ViewEventBus {
    constructor() {
        this.listeners = new Map();
        this.pending = new Map();
    }

    emit(event, data) {
        const callbacks = this.listeners.get(event);
        if (callbacks) {
            callbacks.forEach(cb => cb(data));
        }
    }

    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, new Set());
        }
        this.listeners.get(event).add(callback);
    }

    off(event, callback) {
        const callbacks = this.listeners.get(event);
        if (callbacks) {
            callbacks.delete(callback);
        }
    }

    setPending(event, data) {
        this.pending.set(event, data);
    }

    getPending(event) {
        return this.pending.get(event);
    }

    clearPending(event) {
        this.pending.delete(event);
    }

    consumePending(event) {
        const data = this.pending.get(event);
        this.pending.delete(event);
        return data;
    }
}

// Owns the frontend's mutable runtime state: the view-event bus, the GoldenLayout
// instance, and the active OrdecClient. Constructed once at boot (main.js) and
// exposed as window.ordecApp for tests/debugging. Views reach the bus via
// resultViewer.client.app.eventBus.
export class OrdecApp {
    constructor({ layout, setStatus, onSessionLost }) {
        this.eventBus = new ViewEventBus();
        this.layout = layout;
        this.setStatus = setStatus;
        this.onSessionLost = onSessionLost;
        this.client = null;
    }

    startClient(srctype, resultViewers) {
        const client = new OrdecClient(srctype, resultViewers,
            this.setStatus, this.onSessionLost);
        client.app = this;
        this.client = client;
        return client;
    }
}
