Web UI internals
================

This page documents the internal architecture of the web UI for developers: the client–server protocol, the frontend module structure, and — in detail — the view event bus that coordinates the viewers, including its unintuitive properties. The user-facing introduction is at :doc:`/webui`.

Components
----------

* **Backend** (``src/ordec/server.py``): a WebSocket server that evaluates ORD/Python sources, discovers views, and serializes view data to the browser. In production it also serves the static frontend from ``src/ordec/webdist.tar``; during development, a separate Vite dev server (``cd web && npm run dev``) serves the frontend with hot reload while ``ordec -b`` provides only the backend.
* **Frontend** (``web/src/``): vanilla JS built with Vite, using `Golden Layout <https://golden-layout.com/>`_ for the tabbed/split panel arrangement.

.. note::

    The web tests (``pytest -m web``) run against the **built** bundle, but rebuild it automatically: the ``web`` fixture runs ``npm run build`` whenever ``web/dist`` is missing or older than the sources under ``web/src/`` (and ``package.json``/``vite.config.js``), so no manual build step is needed. This requires ``npm`` on ``PATH``; if a rebuild is needed and ``npm`` is unavailable, the web tests fail rather than silently running against a stale bundle.

Frontend module map
-------------------

``main.js``
    Entry point: Golden Layout setup, toolbar, editor, opening/focusing result views, event-bus wiring for ``*:request-open`` events.
``client.js``
    ``OrdecClient``: WebSocket connection, view list, concurrent view requests (tracked per request id in ``inflight``), dispatch of view results and progress updates to result viewers.
``auth.js``
    Session/auth token management, HMAC verification of module/view query parameters in local mode.
``resultviewer.js``
    ``ResultViewer`` (one per Golden Layout panel: view selector + content area), which instantiates a per-type view class from ``view/``.
``view/``
    The per-type view classes, keyed by the ``type`` field of view messages via the ``viewClassOf`` registry in ``view/index.js`` and sharing the ``View`` base in ``view/view.js``: schematic/symbol SVG viewer (``svg.js``), WebGL layout renderer (``layout.js``), DRC/LVS report viewers (``drc.js`` / ``lvs.js``), and generic report elements including D3 simulation plots (``report.js`` / ``report-elements.js`` / ``report-simplot.js``). ``siformat.js`` (SI formatting) lives here too, alongside the layout renderer's GLSL shaders in ``glsl/``.
``hier-selector.js``
    Hierarchical path selector for browsing simulation results.
``app.js``
    ``OrdecApp``, which owns the frontend runtime state, including its ``eventBus`` (see below).
``theme.js``, ``ace-ord-mode.js``
    Helpers: colors, ORD syntax highlighting.

For automated browser tests, ``main.js`` exposes ``window.ordecApp`` (with ``.client`` and ``.eventBus``), and each ``ResultViewer`` provides ``testInfo()``; see ``tests/test_web.py`` and ``tests/test_web_eventbus.py``.

Client–server protocol
----------------------

All communication runs over one WebSocket (``/api/websocket``) with JSON messages:

1. On connect, the client authenticates and submits the source: ``{msg: 'source', srctype, src, auth}`` (integrated mode, code from the browser editor) or ``{msg: 'localmodule', module, auth}`` (local mode, module on the server's filesystem).
2. The server builds the cells, discovers all views (``discover_views``: every view generator — ``@viewgen``/``@viewgen_noctx``, as Cell method or module-level function — reachable from the module) and answers with ``{msg: 'viewlist', views: [...]}`` — or ``{msg: 'exception', exception}`` if evaluation failed.
3. For each result panel that has a view selected, the client requests ``{msg: 'getview', view: <view name>, req: <id>}``. ``req`` is a client-chosen id, unique per connection; multiple requests may be in flight at once (the client tracks them in the ``inflight`` map). The server hands each request to its *job runner* (``src/ordec/jobrunner.py``), which decides how many view generators run concurrently (``ordec -j N``, default 4; ``-j 0`` evaluates inline without progress/cancel support).
4. While a view generates, the server may push ``{msg: 'viewprogress', req, view, status, fraction, detail}`` messages (rate-limited to ~10/s): ``status`` is a message like ``"Transient simulation"``, ``fraction`` a value in [0, 1] for the progress bar or ``null`` if unknown, and ``detail`` free-form text shown next to the bar (or ``null``). Only ``status`` changes bypass the rate limit, so values that change on every update — like the ``"1.35ms / 500ms"`` of simulated time that a ``tran`` reports — belong in ``detail``, not in ``status``. They come from ``progress()`` calls (``src/ordec/core/genrun.py``) inside the view generator; the ngspice batch runner emits them automatically during ``tran`` by watching the growing rawfile.
5. The server answers every ``getview`` with exactly one terminal ``{msg: 'view', req, view, ...}`` message carrying either ``type`` + ``data`` (``type`` selects the frontend view class, ``data`` is the output of the view's ``webdata()`` method), an ``exception`` field (error during view generation), or ``cancelled: true``. ``exception`` values — here and in the ``{msg: 'exception'}`` message above — are structured traceback dicts (``format_user_exception`` in ``src/ordec/server.py``: exception type, message, frames, syntax error position, plain-text fallback) rendered by ``resultviewer.js``; a few internal error paths send plain strings instead.
6. The client can abort an in-flight generation with ``{msg: 'cancelview', req}`` (idempotent; unknown ids are ignored). Cancellation is cooperative with escalation (see ``ThreadedJobRunner.cancel``): cancel flag → kill of registered external-tool subprocesses (e.g. ngspice) → optional async-exception injection for runaway Python loops (disable by setting ``ordec.jobrunner.ASYNC_CANCEL_ENABLED`` to False). The terminal message of a cancelled request has ``cancelled: true``; the panel then shows a "View generation cancelled." overlay and is not auto-re-requested until the user refreshes it.
7. In local mode, the server watches the source files with inotify and pushes ``{msg: 'localmodule_changed'}``, upon which the client reconnects (unless auto-refresh is disabled). Disconnecting cancels all in-flight generations of that connection, so the rebuild does not wait behind stale long-running simulations.

View names are evaluated with ``eval()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The server does not look up view names in a table; ``query_view()`` in ``server.py`` evaluates the requested view name as a **Python expression** in the connection's module globals (``eval(view_name, conn_globals, conn_globals)``). ``MyCell().schematic`` is therefore just the common case — any expression that evaluates to a subgraph with a ``webdata()`` method works.

This is load-bearing for the LVS viewer: an ``LvsReport`` references the compared layout/schematic subgraphs of *subcircuit pairs* only via nodes inside the report subgraph, and the frontend addresses them with view expressions like ``MyCell().lvs_report.subgraph.cursor_at(<nid>).ref_layout``. Anything reachable from the report can be opened as a view this way, without server-side support code.

(Arbitrary expression evaluation is intentional and consistent with the security model: it is only reachable on an authenticated WebSocket, and the authenticated user may execute arbitrary code by design.)

Version-matched documentation links
-----------------------------------

The landing page (``web/index.html``) links into the documentation on Read the Docs. Because a given ORDeC install may be an older release, these links must point at the docs slug matching the *installed* version rather than always at ``latest``.

The slug is computed server-side by ``doc_url()`` in ``src/ordec/version.py`` (``vX.Y.Z`` for releases, ``latest`` for development/unknown versions) and served as ``docs_url`` alongside ``version`` by ``/api/version``. In the markup, each documentation link carries a ``data-docs-page`` attribute naming the target page relative to the docs root (e.g. ``webui.html``; empty means the docs root) and has **no** static ``href``. The inline script rewrites every ``a[data-docs-page]`` on load, setting ``href = docs_url + dataset.docsPage``.

Keeping the links href-less makes ``doc_url()`` the single source of truth for the documentation URL: there is no hard-coded URL in the markup to drift out of sync. The trade-off is that the links only become clickable once ``/api/version`` has been fetched (fine for a page served by that same backend).

The view event bus
------------------

``app.js`` provides ``OrdecApp.eventBus`` (a ``ViewEventBus`` instance, reached from a view via ``resultViewer.client.app.eventBus``), a minimal pub/sub hub that lets viewers in *different Golden Layout panels* talk to each other (e.g. "highlight this DRC violation in the layout viewer"). API: ``emit(event, data)``, ``on(event, cb)``, ``off(event, cb)``, plus a *pending* store (``setPending``, ``getPending``, ``consumePending``, ``clearPending``) for delivering a payload to viewers that are not open yet.

Events
~~~~~~

============================ ============================== ====================================================================================================
Event                        Emitter → Listener             Meaning / payload
============================ ============================== ====================================================================================================
``drc:select``               DRC viewer → layout viewer     Highlight a DRC violation; payload has the violation geometry. Pending key: ``drc:select`` (consumed once).
``drc:clear``                DRC viewer → layout viewer     Remove DRC highlight.
``lvs:layout-select``        LVS viewer → layout viewer     Highlight an LVS item in the layout. Payload: ``{pos, schem_nid, item_type, schem_name, layoutView, schemView}``.
``lvs:schem-select``         LVS viewer → schematic viewer  Highlight an LVS item in the schematic (same payload).
``lvs:clear``                LVS viewer → both              Remove LVS highlights.
(pending key ``lvs:select``) LVS viewer → late viewers      Last selection payload, applied by layout/schematic viewers that open after the click (kept, not consumed — see below).
``layout:request-open``      any viewer → ``main.js``       Open (or focus) a result panel showing ``data.view``; ``data.sourceContainer`` controls split placement.
``schematic:request-open``   any viewer → ``main.js``       Same for schematics.
``lvs:request-open-views``   LVS viewer → ``main.js``       Open layout and/or schematic panels (``{layoutView, schemView, sourceContainer}``) side by side.
============================ ============================== ====================================================================================================

Opening new viewers from a viewer (open-and-highlight flow)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When a report viewer (DRC, LVS) wants to highlight an object in a layout or schematic, the target viewer may not be open yet. A viewer cannot create panels itself — panel management lives in ``main.js`` — and it cannot deliver a highlight synchronously to a panel whose content does not exist yet. The flow that solves both problems:

1. **Derive the target view expression.** The initiating viewer builds the view name of the layout/schematic to open from its *own* ``viewName``, by appending attribute accesses: e.g. ``${this.viewName}.ref_layout`` for the report's layout, or ``${this.viewName}.subgraph.cursor_at(${nid}).ref_layout`` for the layout of an LVS subcircuit pair. This works because view names are Python expressions evaluated by the server (see above) — any subgraph reachable from the report can be named this way, without the server knowing about it in advance.
2. **Always emit the select event.** The viewer emits the select event (``lvs:layout-select`` / ``lvs:schem-select``); any already-open target viewer highlights immediately. Whether a *new* panel should also be opened is a property of the triggering action, not of the current listeners — see the next step.
3. **Otherwise, park the payload and request a panel.** The viewer stores the selection payload in the pending store (``setPending``) and emits ``layout:request-open`` / ``schematic:request-open`` (or ``lvs:request-open-views`` for a layout+schematic pair at once), passing the view expression and its own Golden Layout container as ``sourceContainer`` (available on view classes as ``this.panelContainer``). The pending store is what bridges the asynchronous gap: an event emitted now would simply be lost, since the future viewer is not subscribed yet.
4. **main.js opens or focuses the panel.** The ``*:request-open`` handlers first look for an existing result panel whose selected view equals the requested expression (``findResultViewerByView``) and focus it instead of duplicating it. Otherwise they add a new ``result`` component with ``componentState: {view, directView: true}``, placed in a split next to the requesting panel (derived from ``sourceContainer``); ``lvs:request-open-views`` stacks layout and schematic in one column.
5. **Direct-view panels skip the view selector.** A ``ResultViewer`` created with ``directView: true`` has no view dropdown/hierarchy selector — it shows a fixed label with the view expression, immediately requests its view, and ignores the auto-refresh gating that normal panels apply.
6. **The view data arrives via the normal protocol.** The new panel enters the client's sequential ``getview`` queue; the server ``eval()``'s the expression and returns the rendered view data; ``updateView()`` constructs the view class as ``new ViewClass(resContent, viewName, resultViewer, panelContainer)`` and then calls ``update(msgData, wireHash)``.
7. **The new viewer picks up the pending payload.** In its constructor it reads the pending selection (``getPending``) and applies the highlight during ``update()`` — not in the constructor, where there is no rendered content to highlight in yet and the wire hash of the shown subgraph is not known (see pitfalls below).

For a complete reference implementation of this flow, see the DRC viewer's marker click handler (``view/drc.js``) and the LVS viewer's ``_attachEventHandlers()`` (``view/lvs.js``), and the corresponding pending-consumption code in ``view/layout.js``.

Targeted vs. broadcast selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

LVS item payloads carry positions (layout) and node ids (schematic) that are only meaningful **relative to one specific subgraph**. For the report's *top-level* circuit pair, the payload is broadcast with ``layoutView``/``schemView`` set to ``null``, and every open layout/schematic viewer highlights (an open view of the top cell is correct regardless of the view expression it was opened under). For *subcircuit* pairs, the payload carries the pair's view expressions (``<report view>.subgraph.cursor_at(<circuit nid>).ref_layout`` / ``.ref_schematic``), and listeners must filter: a viewer ignores the event unless the target view name equals its own ``viewName``. Without this filtering, nids and positions of different subgraphs would collide and highlight nonsense in unrelated viewers.

Pitfalls
~~~~~~~~

Hard-won properties of this design — read before touching viewer event code:

* **Identity comes from the constructor, view data from update().** ``ResultViewer.updateView()`` passes what stays fixed for the instance (``resContent``, ``viewName``, ``resultViewer``, ``panelContainer``) to the constructor, and what comes with each view message (``msgData``, ``wireHash``) to ``update()``; it never assigns onto a view from the outside. Every view class spells out both signatures in full, including arguments it does not use. The wire hash is per-message because a view instance is reused across regenerations that give it a new subgraph. Consequence for pending selections: the layout and schematic viewers stash ``this.eventBus.getPending('lvs:select')`` in the constructor and filter it against ``viewName``/``wireHash`` when they apply it in ``update()`` — the view name would already allow filtering earlier, the wire hash arrives only with the data.
* **The LVS pending payload must not be consume-once.** A single LVS item click may open *two* viewers (layout and schematic), and both need the same pending payload — hence ``getPending`` + an explicit ``clearPending('lvs:select')`` on deselect, in contrast to the DRC viewer which uses ``consumePending`` (only one target viewer).
* **Opening a panel is driven by an explicit flag, not by the listeners.** ``emitSelection(item, circuitMap, data, open)`` always emits the select event (broadcast to open viewers) but only emits ``lvs:request-open-views`` when ``open`` is set: re-selecting the current row highlights in place (``open`` false), while activating an item opens or focuses its panels (``open`` true). ``request-open-views`` itself focuses an already-open target — matched by view name or wire hash — instead of duplicating it, so this stays correct for subcircuit pairs, which always carry their own (named) views.
* **Event handlers are attached in a separate method from rendering.** The LVS viewer builds its DOM in ``update()`` but attaches handlers in ``_attachEventHandlers(itemMap, circuitMap)``; every lookup table the handlers need must be passed explicitly. A handler referencing a variable that only exists in the rendering scope fails with an *uncaught ReferenceError visible only in the browser console* — the UI just silently does nothing. When debugging "click has no effect", check the browser console first.
* **destroy() must mirror every on().** Golden Layout creates and destroys view instances as panels open and close. A view class that subscribes in its constructor must unsubscribe in ``destroy()``, otherwise stale listeners of closed panels keep reacting to events.
