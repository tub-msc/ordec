// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { session } from './auth';
import type { ServerMessage, ViewInfo } from './types';

export interface ResultViewerLike {
    registerClient(client: OrdecClient): void;
    updateViewListAndException(): void;
    requestsView(): boolean;
    viewSelected: string | null;
    updateView(msg: any): void;
}

export class OrdecClient {
    views: Map<string, ViewInfo>;
    reqPending: boolean;
    srctype: string;
    src: string;
    resultViewers: ResultViewerLike[];
    setStatus: (status: string) => void;
    localModule: string | null;
    exception: string | null;
    sock: WebSocket | null;
    nextView: ResultViewerLike | null;

    constructor(srctype: string, resultViewers: ResultViewerLike[], setStatus: (status: string) => void) {
        this.views = new Map();
        this.reqPending = false;
        this.srctype = srctype;
        this.src = ""; // set by Editor from the outside
        this.registerResultViewers(resultViewers);
        this.setStatus = setStatus;
        this.localModule = null; // Set to module name when in localModule mode.
        this.exception = null;
        this.sock = null;
        this.nextView = null;
    }

    registerResultViewers(resultViewers: ResultViewerLike[]): void {
        // Ensures that each x in this.resultViewers has x.client set.
        resultViewers.forEach(rv => {
            rv.registerClient(this);
        });
        this.resultViewers = resultViewers;
    }

    connect(): void {
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

    wsOnMessage(messageEvent: MessageEvent): void {
        const msg: ServerMessage = JSON.parse(messageEvent.data);
        if (msg.msg == 'viewlist') {
            this.exception = null;
            this.views.clear();
            msg.views.forEach(view => {
                this.views.set(view.name, view);
            });
            this.resultViewers.forEach(rv => rv.updateViewListAndException());
            this.requestNextView();
        } else if (msg.msg == 'exception') {
            this.exception = msg.exception;
            this.setStatus('exception');
            this.resultViewers.forEach(rv => rv.updateViewListAndException());
            this.requestNextView();
        } else if (msg.msg == 'view') {
            this.nextView!.updateView(msg);
            this.reqPending = false;
            this.requestNextView();
        } else if (msg.msg == 'localmodule_changed') {
            console.log("ordecClient.connect() triggered by localmodule_changed message.");
            this.connect();
        }
    }

    wsOnClose(closeEvent: CloseEvent): void {
        if (!this.exception) {
            this.setStatus('disconnected');
        }
    }

    wsOnOpen(event: Event): void {
        let msg: Record<string, any>;
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
        this.sock!.send(JSON.stringify(msg));
    }

    requestNextView(): void {
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
            this.setStatus('busy');
            this.sock!.send(JSON.stringify({
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
