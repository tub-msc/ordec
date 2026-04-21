// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

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

    hasListeners(event) {
        const callbacks = this.listeners.get(event);
        return callbacks && callbacks.size > 0;
    }

    setPending(event, data) {
        this.pending.set(event, data);
    }

    consumePending(event) {
        const data = this.pending.get(event);
        this.pending.delete(event);
        return data;
    }
}

export const viewEventBus = new ViewEventBus();
