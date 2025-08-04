// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

export class OrdecClient {
    constructor(srctype, resultViewers, setStatus) {
        this.views = [];
        this.reqPending = false;
        this.srctype = srctype;
        this.src = ""; // set by Editor from the outside
        this.resultViewers = resultViewers;
        this.setStatus = setStatus;
    }

    getAuthCookie() {
        let authCookie = '';
        document.cookie.split(';').forEach(el => {
            let split = el.split('=');
            if(split[0].trim() == 'ordecAuth') {
                authCookie = split.slice(1).join("=");
            }
        })
        return authCookie;
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
        if (msg['msg'] == 'views') {
            this.exception = null;
            this.views = msg['views'];
            this.resultViewers.forEach(rv => rv.updateGlobalState());
            this.requestNextView();
        } else if (msg['msg'] == 'exception') {
            this.exception = msg['exception'];
            this.setStatus('exception');
            this.resultViewers.forEach(rv => rv.updateGlobalState());
            this.requestNextView();
        } else if (msg['msg'] == 'view') {
            this.nextView.updateView(msg);
            this.reqPending = false;
            this.requestNextView();
        }
    }

    wsOnClose(closeEvent) {
        if (!this.exception) {
            //this.exception = "Websocket disconnected.";
            this.setStatus('disconnected');
        }
    }

    wsOnOpen(event) {
        this.setStatus('busy');
        this.sock.send(JSON.stringify({
            msg: 'source',
            srctype: this.srctype,
            src: this.src,
            auth: this.getAuthCookie(),
        }));
    }

    requestNextView() {
        if (this.reqPending) {
            return;
        }

        this.nextView = null;
        this.resultViewers.some((rv) => {
            if (!rv.viewLoaded && rv.viewRequested) {
                this.nextView = rv;
                return true; // = "break;" in some()
            }
        })

        if (this.nextView) {
            //console.log('next view', nextView.viewRequested)
            this.sock.send(JSON.stringify({
                msg: 'getview',
                view: this.nextView.viewRequested,
            }));
            this.reqPending = true;
        } else {
            if (!this.exception) {
                this.setStatus('ready');
            }
        }
    }
}
