// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { Encoder } from 'cbor-x';
import { session, reloadAuthKey } from './auth.js';

// All WebSocket messages are CBOR binary frames, in both directions (see
// server.py). Maps decode to plain objects and 64-bit integers to numbers,
// as with JSON; RFC 8746 typed-array tags decode to typed arrays.
const cbor = new Encoder({useRecords: false, mapsAsObjects: true, int64AsNumber: true});

export class OrdecClient {
    constructor(srctype, resultViewers, setStatus, onSessionLost) {
        this.views = new Map();
        // In-flight view requests: req id -> ResultViewer. Multiple requests
        // may be in flight at once; the server's pass manager decides how
        // many run concurrently.
        this.inflight = new Map();
        // In-flight setlayoutstyle and setconfig requests: req id -> callback.
        this.saveRequests = new Map();
        // The user's configuration file (see src/ordec/config.py), as sent
        // with the view list and changed by setConfig.
        this.config = {};
        // The files whose statements moveNode may change, as sent with the
        // view list (see source_files in src/ordec/server.py).
        this.srcfiles = [];
        this.reqCounter = 0;
        this.srctype = srctype;
        this.src = ""; // set by Editor from the outside
        // The source string actually sent to the server for the build whose
        // results are coming in (null in local mode). Consumers that pair a
        // result with its source (course.js pushScore) must use this rather
        // than the live editor content, which may have moved on meanwhile.
        this.srcBuilt = null;
        // Course mode: epilogue source binding the lesson's check as the
        // lesson() view, executed server-side after src (see course.js).
        this.checkSrc = null;
        // True from connect() until the server answers the build with a
        // viewlist or an exception (or the socket fails). Keeps the status
        // at 'busy' meanwhile: without it, the status would read 'ready'
        // while the views of the previous build are still listed.
        this.buildPending = false;
        this.registerResultViewers(resultViewers);
        this.setStatus = setStatus;
        // Called when a hub-hosted instance is culled and cannot be
        // reconnected to; main.js shows the restart overlay (see showSessionLost).
        this.onSessionLost = onSessionLost;
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
        // Relative to the document URL so the app works under a URL path
        // prefix (e.g. /user/<name>/ behind JupyterHub) as well as at /.
        const wsUrl = new URL('api/websocket', document.baseURI);
        if(wsUrl.protocol=='http:') {
            wsUrl.protocol = 'ws:';
        } else {
            wsUrl.protocol = 'wss:';
        }
        this.sock = new WebSocket(wsUrl.href, []);
        this.sock.binaryType = 'arraybuffer';
        this.sockOpened = false;
        // Set once the server answers with an 'exception' message on this
        // socket (see wsOnClose).
        this.sockException = false;
        this.sock.onopen = (ev) => this.wsOnOpen(ev);
        this.sock.onmessage = (ev) => this.wsOnMessage(ev);
        this.sock.onclose = (ev) => this.wsOnClose(ev);
        this.sock.onerror = (ev) => this.wsOnError(ev);
        this.inflight.clear();
        this.failSaveRequests();
        this.buildPending = true;
        this.updateStatus();
    }

    wsOnMessage(messageEvent) {
        if (messageEvent.target !== this.sock) {
            return;
        }
        const msg = cbor.decode(new Uint8Array(messageEvent.data));
        //console.log(msg)
        if (msg['msg'] == 'viewlist') {
            this.buildPending = false;
            this.exception = null;
            // Successful build: clear the error annotation in the editor.
            this.app?.eventBus.emit('editor:build-exception', null);
            this.views.clear();
            this.config = msg['config'] ?? {};
            this.app?.eventBus.emit('config:change', this.config);
            this.srcfiles = msg['srcfiles'];
            msg['views'].forEach(view => {
                this.views.set(view.name, view);
            });
            // freshViewlist=true: a view selected in a viewer but absent
            // from this authoritative list is really gone (deselect it),
            // as opposed to the list merely being stale or not yet loaded.
            this.resultViewers.forEach(rv => rv.updateViewListAndException(true));
            this.requestViews();
        } else if (msg['msg'] == 'exception') {
            // Structured exception dict (see server.py
            // format_user_exception / message_exception).
            this.buildPending = false;
            this.sockException = true;
            this.exception = msg['exception'];
            this.setStatus('exception');
            // Build errors annotate the failing line in the editor (main.js).
            this.app?.eventBus.emit('editor:build-exception', this.exception);
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
        } else if (['setlayoutstyle', 'setconfig', 'movenode'].includes(msg['msg'])) {
            const onReply = this.saveRequests.get(msg['req']);
            this.saveRequests.delete(msg['req']);
            onReply?.(msg.exception ?? null, msg);
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
        // Events from a socket that connect() already replaced are stale;
        // acting on them would clobber the state of the current socket.
        if (closeEvent.target !== this.sock) {
            return;
        }
        // All in-flight requests are gone once the socket closes. Reset so a
        // reconnect doesn't get stuck waiting for responses that will never
        // arrive.
        this.inflight.clear();
        this.failSaveRequests();
        this.buildPending = false;
        if (session.hubMode && !this.sockOpened) {
            // Hub-hosted and the socket never opened: the server instance
            // was culled or stopped; reconnecting is futile. A page reload
            // goes through the hub, which respawns the instance.
            this.onSessionLost?.();
        }
        if (!this.sockException) {
            // The server closes the socket on its own only after an
            // 'exception' message (e.g. a wrong auth token), which stays on
            // display. Any other close means the server is unreachable: show
            // this in the viewers, which would otherwise keep showing stale
            // views. Same dict shape and etype as server.py message_exception.
            const message = this.sockOpened
                ? 'Lost connection to server.'
                : 'Could not connect to server.';
            this.exception = {
                etype: 'Error',
                message: message,
                text: message,
                frames: [],
            };
            this.resultViewers.forEach(rv => rv.updateViewListAndException());
        }
        this.updateStatus();
    }

    wsOnError(errorEvent) {
        if (errorEvent.target !== this.sock) {
            return;
        }
        // The close event that always follows handles the failure.
        console.error("WebSocket error:", errorEvent);
    }

    wsOnOpen(event) {
        if (event.target !== this.sock) {
            return;
        }
        this.sockOpened = true;
        let msg;
        reloadAuthKey();
        if(this.localModule) {
            // Local mode:
            this.srcBuilt = null;
            msg = {
                msg: 'localmodule',
                module: this.localModule,
                auth: session.authKey,
            };
        } else {
            this.srcBuilt = this.src;
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
        this.sock.send(cbor.encode(msg));
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
                rv.beginRequest(req);
                this.inflight.set(req, rv);
                this.sock.send(cbor.encode({
                    msg: 'getview',
                    view: rv.viewSelected,
                    req: req,
                }));
            });
        }
        this.updateStatus();
    }

    // Pending save requests get no answer once the socket is gone.
    failSaveRequests() {
        this.saveRequests.forEach(onReply =>
            onReply({etype: 'Error', message: 'Connection to the server lost before saving.'}));
        this.saveRequests.clear();
    }

    // Changes the user's customization of the LayoutStyle with the given key
    // (settings and layers as in update_customization in
    // src/ordec/layout/style.py). onReply(exception) is called with the
    // server's answer: null once the file is written, else the exception.
    setLayoutStyle(key, settings, layers, onReply) {
        if (this.exception || !this.sock || this.sock.readyState != WebSocket.OPEN) {
            onReply({etype: 'Error', message: 'Not connected to the server.'});
            return;
        }
        const req = ++this.reqCounter;
        this.saveRequests.set(req, onReply);
        this.sock.send(cbor.encode({
            msg: 'setlayoutstyle',
            key: key,
            req: req,
            settings: settings,
            layers: layers,
        }));
    }

    // Changes a setting of the user's configuration file (see update_config
    // in src/ordec/config.py; value null removes it): applied by all viewers
    // right away (config:change), and saved by the server. onReply as in
    // setLayoutStyle.
    setConfig(table, name, value, onReply) {
        this.config = {...this.config, [table]: {...this.config[table], [name]: value}};
        this.app?.eventBus.emit('config:change', this.config);
        if (this.exception || !this.sock || this.sock.readyState != WebSocket.OPEN) {
            onReply({etype: 'Error', message: 'Not connected to the server.'});
            return;
        }
        const req = ++this.reqCounter;
        this.saveRequests.set(req, onReply);
        this.sock.send(cbor.encode({
            msg: 'setconfig',
            req: req,
            table: table,
            name: name,
            value: value,
        }));
    }

    // Moves the schematic instance or port whose ORD statement starts at line
    // and column of file by (dx, dy) (see move_node in src/ordec/server.py).
    // onReply(exception, reply) as in setLayoutStyle; the reply carries the
    // edit of the source as start, end and text.
    moveNode(file, line, column, dx, dy, onReply) {
        if (this.exception || !this.sock || this.sock.readyState != WebSocket.OPEN) {
            onReply({etype: 'Error', message: 'Not connected to the server.'});
            return;
        }
        // The server would edit the source of the pending build, whose lines
        // may differ from those of the shown views.
        if (this.buildPending) {
            onReply({etype: 'Error', message: 'Cannot move: the design is being rebuilt.'});
            return;
        }
        const req = ++this.reqCounter;
        this.saveRequests.set(req, onReply);
        this.sock.send(cbor.encode({
            msg: 'movenode',
            req: req,
            file: file,
            line: line,
            column: column,
            dx: dx,
            dy: dy,
        }));
    }

    cancelView(rv) {
        // Idempotent; the in-flight entry is only removed by the terminal
        // 'view' message (which a cancel always produces).
        if (this.inflight.has(rv.currentReq)) {
            this.sock.send(cbor.encode({
                msg: 'cancelview',
                req: rv.currentReq,
            }));
        }
    }

    updateStatus() {
        if (this.buildPending) {
            this.setStatus('busy');
        } else if (this.exception) {
            // Without an 'exception' message on the current socket, the
            // exception is the connection error set by wsOnClose.
            this.setStatus(this.sockException ? 'exception' : 'disconnected');
        } else if (this.inflight.size > 0) {
            this.setStatus('busy');
        } else {
            this.setStatus('ready');
        }
    }
}
