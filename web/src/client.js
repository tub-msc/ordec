// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { session } from './auth.js';

export class OrdecClient {
    constructor(srctype, resultViewers, setStatus) {
        this.views = new Map();
        // In-flight view requests: req id -> ResultViewer. Multiple requests
        // may be in flight at once; the server's pass manager decides how
        // many run concurrently.
        this.inflight = new Map();
        this.reqCounter = 0;
        this.srctype = srctype;
        this.src = ""; // set by Editor from the outside
        // Course mode: epilogue source binding the lesson's check as the
        // lesson() view, executed server-side after src (see course.js).
        this.checkSrc = null;
        this.registerResultViewers(resultViewers);
        this.setStatus = setStatus;
        this.localModule = null; // Set to module name when in localModule mode.
        this.autoRefreshEnabled = true;
    }

    registerResultViewers(resultViewers) {
        // Ensures that each x in this.resultViewers has x.client set.
        resultViewers.forEach(rv => {
            rv.registerClient(this);
        });
        this.resultViewers = resultViewers;
        // Only request views after viewlist received (views.size > 0) to avoid race with initial load
        if (this.sock && this.views.size > 0) {
            this.requestViews();
        }
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
        this.sock.onopen = (ev) => this.wsOnOpen(ev);
        this.sock.onmessage = (ev) => this.wsOnMessage(ev);
        this.sock.onclose = (ev) => this.wsOnClose(ev);
        this.sock.onerror = (ev) => this.wsOnError(ev);
        this.inflight.clear();
    }

    wsOnMessage(messageEvent) {
        const msg = JSON.parse(messageEvent.data);
        //console.log(msg)
        if (msg['msg'] == 'viewlist') {
            this.exception = null;
            this.views.clear();
            msg['views'].forEach(view => {
                this.views.set(view.name, view);
            });
            this.resultViewers.forEach(rv => rv.updateViewListAndException());
            this.requestViews();
        } else if (msg['msg'] == 'exception') {
            this.exception = msg['exception'];
            this.setStatus('exception');
            this.resultViewers.forEach(rv => rv.updateViewListAndException());
        } else if (msg['msg'] == 'view') {
            // Terminal message: exactly one per request. Always remove the
            // request and advance, even if a viewer throws while rendering:
            // otherwise one broken view (e.g. a report probe) would wedge
            // the requests of all viewers.
            const rv = this.inflight.get(msg['req']);
            this.inflight.delete(msg['req']);
            try {
                rv?.updateView(msg);
            } finally {
                this.requestViews();
            }
        } else if (msg['msg'] == 'viewprogress') {
            this.inflight.get(msg['req'])?.updateProgress(msg);
        } else if (msg['msg'] == 'localmodule_changed') {
            if (this.autoRefreshEnabled) {
                console.log("ordecClient.connect() triggered by localmodule_changed message.");
                this.connect();
            } else {
                console.log("localmodule_changed ignored (auto-refresh disabled).");
            }
        }
    }

    wsOnClose(closeEvent) {
        // All in-flight requests are gone once the socket closes. Reset so a
        // reconnect doesn't get stuck waiting for responses that will never
        // arrive.
        this.inflight.clear();
        if (!this.exception) {
            //this.exception = "Websocket disconnected.";
            this.setStatus('disconnected');
        }
    }

    wsOnError(errorEvent) {
        console.error("WebSocket error:", errorEvent);
        this.inflight.clear();
        if (!this.exception) {
            this.setStatus('disconnected');
        }
    }

    wsOnOpen(event) {
        let msg;
        this.setStatus('busy');
        if(this.localModule) {
            // Local mode:
            msg = {
                msg: 'localmodule',
                module: this.localModule,
                auth: session.authKey,
            };
        } else {
            // Integrated mode:
            msg = {
                msg: 'source',
                srctype: this.srctype,
                src: this.src,
                auth: session.authKey,
            };
            if (this.checkSrc) {
                msg.check_src = this.checkSrc;
            }
        }
        this.sock.send(JSON.stringify(msg));
    }

    requestViews() {
        // Dispatch a request for every viewer that wants one and has none in
        // flight yet. Unlike the previous one-at-a-time protocol, requests
        // are not serialized; the server queues them in its pass manager.
        if (!this.exception && this.sock && this.sock.readyState == WebSocket.OPEN) {
            this.resultViewers.forEach(rv => {
                if (this.inflight.has(rv.currentReq) || !rv.requestsView()) {
                    return;
                }
                const req = ++this.reqCounter;
                rv.currentReq = req;
                this.inflight.set(req, rv);
                this.sock.send(JSON.stringify({
                    msg: 'getview',
                    view: rv.viewSelected,
                    req: req,
                }));
            });
        }
        this.updateStatus();
    }

    cancelView(rv) {
        // Idempotent; the in-flight entry is only removed by the terminal
        // 'view' message (which a cancel always produces).
        if (this.inflight.has(rv.currentReq)) {
            this.sock.send(JSON.stringify({
                msg: 'cancelview',
                req: rv.currentReq,
            }));
        }
    }

    updateStatus() {
        if (this.exception) {
            this.setStatus('exception');
        } else if (this.inflight.size > 0) {
            this.setStatus('busy');
        } else {
            this.setStatus('ready');
        }
    }
}
