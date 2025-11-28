// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { session } from './auth.js';

export class OrdecClient {
    constructor(srctype, resultViewers, setStatus) {
        this.views = new Map();
        this.reqPending = false;
        this.srctype = srctype;
        this.src = ""; // set by Editor from the outside
        this.registerResultViewers(resultViewers);
        this.setStatus = setStatus;
        this.localModule = null; // Set to module name when in localModule mode.
    }

    registerResultViewers(resultViewers) {
        // Ensures that each x in this.resultViewers has x.client set.
        resultViewers.forEach(rv => {
            rv.registerClient(this);
        });
        this.resultViewers = resultViewers;
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
        this.reqPending = false;
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
            this.requestNextView();
        } else if (msg['msg'] == 'exception') {
            this.exception = msg['exception'];
            this.setStatus('exception');
            this.resultViewers.forEach(rv => rv.updateViewListAndException());
            this.requestNextView();
        } else if (msg['msg'] == 'view') {
            this.nextView.updateView(msg);
            this.reqPending = false;
            this.requestNextView();
        } else if (msg['msg'] == 'localmodule_changed') {
            console.log("ordecClient.connect() triggered by localmodule_changed message.");
            this.connect();
        }
    }

    wsOnClose(closeEvent) {
        if (!this.exception) {
            //this.exception = "Websocket disconnected.";
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
        }
        this.sock.send(JSON.stringify(msg));
    }

    requestNextView() {
        if (this.reqPending || this.exception) {
            return;
        }

        this.nextView = null;
        this.resultViewers.some((rv) => {
            if (rv.requestsView()) {
                this.nextView = rv;
                return true; // = "break;" in some()
            }
        })

        if (this.nextView) {
            //console.log('next view', nextView.viewRequested)
            this.setStatus('busy');
            this.sock.send(JSON.stringify({
                msg: 'getview',
                view: this.nextView.viewSelected,
            }));
            this.reqPending = true;
        } else {
            if (!this.exception) {
                this.setStatus('ready');
            }
        }
    }
}
