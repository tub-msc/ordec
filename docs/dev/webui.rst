Web UI internals
================

This page documents the internal architecture of the web UI for developers: the client–server protocol, the frontend module structure, and — in detail — the view event bus that coordinates the viewers, including its unintuitive properties. The user-facing introduction is at :doc:`/webui`.

Components
----------

* **Backend** (``ordec/server.py``): a WebSocket server that evaluates ORD/Python sources, discovers views, and serializes view data to the browser. In production it also serves the static frontend from ``ordec/webdist.tar``; during development, a separate Vite dev server (``cd web && npm run dev``) serves the frontend with hot reload while ``ordec -b`` provides only the backend.
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
    ``ResultViewer`` (one per Golden Layout panel: view selector + content area) and the per-type view classes (schematic/symbol SVG viewer, DRC viewer, LVS report viewer, plots, HTML, ...), keyed by the ``type`` field of view messages.
``layout-gl.js``
    WebGL-based layout renderer (its own view class).
``simplot.js``
    D3-based interactive simulation plots.
``hier-selector.js``
    Hierarchical path selector for browsing simulation results.
``event-bus.js``
    ``viewEventBus`` singleton (see below).
``viewer-coordinates.js``, ``siformat.js``, ``theme.js``, ``ace-ord-mode.js``
    Helpers: coordinate transforms, SI formatting, colors, ORD syntax highlighting.

For automated browser tests, ``main.js`` exposes ``window.ordecClient`` and ``window.viewEventBus``, and each ``ResultViewer`` provides ``testInfo()``; see ``tests/test_web.py`` and ``tests/test_web_eventbus.py``.

Client–server protocol
----------------------

All communication runs over one WebSocket (``/api/websocket``) with JSON messages:

1. On connect, the client authenticates and submits the source: ``{msg: 'source', srctype, src, auth}`` (integrated mode, code from the browser editor) or ``{msg: 'localmodule', module, auth}`` (local mode, module on the server's filesystem).
2. The server builds the cells, discovers all views (``discover_views``: every ``@generate`` method and ``@generate_func`` function reachable from the module) and answers with ``{msg: 'viewlist', views: [...]}`` — or ``{msg: 'exception', exception}`` if evaluation failed.
3. For each result panel that has a view selected, the client requests ``{msg: 'getview', view: <view name>, req: <id>}``. ``req`` is a client-chosen id, unique per connection; multiple requests may be in flight at once (the client tracks them in the ``inflight`` map). The server hands each request to its *job runner* (``ordec/jobrunner.py``), which decides how many view generators run concurrently (``ordec -j N``, default 4; ``-j 0`` evaluates inline without progress/cancel support).
4. While a view generates, the server may push ``{msg: 'viewprogress', req, view, status, fraction}`` messages (rate-limited to ~10/s): ``status`` is a message like ``"Transient simulation"``, ``fraction`` a value in [0, 1] for the progress bar or ``null`` if unknown. They come from ``progress()`` calls (``ordec/core/genrun.py``) inside the view generator; the ngspice batch runner emits them automatically during ``tran`` by watching the growing rawfile.
5. The server answers every ``getview`` with exactly one terminal ``{msg: 'view', req, view, ...}`` message carrying either ``type`` + ``data`` (``type`` selects the frontend view class, ``data`` is the output of the view's ``webdata()`` method), an ``exception`` field (error during view generation), or ``cancelled: true``.
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

The slug is computed server-side by ``doc_url()`` in ``ordec/version.py`` (``vX.Y.Z`` for releases, ``latest`` for development/unknown versions) and served as ``docs_url`` alongside ``version`` by ``/api/version``. In the markup, each documentation link carries a ``data-docs-page`` attribute naming the target page relative to the docs root (e.g. ``webui.html``; empty means the docs root) and has **no** static ``href``. The inline script rewrites every ``a[data-docs-page]`` on load, setting ``href = docs_url + dataset.docsPage``.

Keeping the links href-less makes ``doc_url()`` the single source of truth for the documentation URL: there is no hard-coded URL in the markup to drift out of sync. The trade-off is that the links only become clickable once ``/api/version`` has been fetched (fine for a page served by that same backend).

The view event bus
------------------

``event-bus.js`` provides the singleton ``viewEventBus``, a minimal pub/sub hub that lets viewers in *different Golden Layout panels* talk to each other (e.g. "highlight this DRC violation in the layout viewer"). API: ``emit(event, data)``, ``on(event, cb)``, ``off(event, cb)``, ``hasListeners(event)``, plus a *pending* store (``setPending``, ``getPending``, ``consumePending``, ``clearPending``) for delivering a payload to viewers that are not open yet.

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
2. **If a suitable viewer is already open, just emit.** If ``viewEventBus.hasListeners('lvs:layout-select')`` (or the targeted viewer is known to be open), emitting the select event is sufficient; no panel needs to be created.
3. **Otherwise, park the payload and request a panel.** The viewer stores the selection payload in the pending store (``setPending``) and emits ``layout:request-open`` / ``schematic:request-open`` (or ``lvs:request-open-views`` for a layout+schematic pair at once), passing the view expression and its own Golden Layout container as ``sourceContainer`` (available on view classes as ``this.glContainer``). The pending store is what bridges the asynchronous gap: an event emitted now would simply be lost, since the future viewer is not subscribed yet.
4. **main.js opens or focuses the panel.** The ``*:request-open`` handlers first look for an existing result panel whose selected view equals the requested expression (``findResultViewerByView``) and focus it instead of duplicating it. Otherwise they add a new ``result`` component with ``componentState: {view, directView: true}``, placed in a split next to the requesting panel (derived from ``sourceContainer``); ``lvs:request-open-views`` stacks layout and schematic in one column.
5. **Direct-view panels skip the view selector.** A ``ResultViewer`` created with ``directView: true`` has no view dropdown/hierarchy selector — it shows a fixed label with the view expression, immediately requests its view, and ignores the auto-refresh gating that normal panels apply.
6. **The view data arrives via the normal protocol.** The new panel enters the client's sequential ``getview`` queue; the server ``eval()``'s the expression and returns the rendered view data; ``updateView()`` instantiates the view class and then assigns ``viewName``/``glContainer``.
7. **The new viewer picks up the pending payload.** In its constructor it reads the pending selection (``consumePending`` for DRC, ``getPending`` for LVS) and applies the highlight during ``update()`` — not in the constructor, because targeted payloads must be filtered against ``viewName``, which is only assigned after construction (see pitfalls below).

For a complete reference implementation of this flow, see the DRC viewer's marker click handler and the LVS viewer's ``_attachEventHandlers()`` in ``resultviewer.js``, and the corresponding pending-consumption code in ``layout-gl.js``.

Targeted vs. broadcast selection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

LVS item payloads carry positions (layout) and node ids (schematic) that are only meaningful **relative to one specific subgraph**. For the report's *top-level* circuit pair, the payload is broadcast with ``layoutView``/``schemView`` set to ``null``, and every open layout/schematic viewer highlights (an open view of the top cell is correct regardless of the view expression it was opened under). For *subcircuit* pairs, the payload carries the pair's view expressions (``<report view>.subgraph.cursor_at(<circuit nid>).ref_layout`` / ``.ref_schematic``), and listeners must filter: a viewer ignores the event unless the target view name equals its own ``viewName``. Without this filtering, nids and positions of different subgraphs would collide and highlight nonsense in unrelated viewers.

Pitfalls
~~~~~~~~

Hard-won properties of this design — read before touching viewer event code:

* **viewName is assigned only after construction.** ``ResultViewer.updateView()`` instantiates a view class and *then* sets ``view.viewName`` (and ``view.glContainer``). A view-class constructor therefore cannot filter targeted payloads by view name. Pattern used by the layout and schematic viewers: stash ``viewEventBus.getPending('lvs:select')`` in the constructor, and apply/filter it at the start of the first ``update()`` call, where ``viewName`` is known.
* **The LVS pending payload must not be consume-once.** A single LVS item click may open *two* viewers (layout and schematic), and both need the same pending payload — hence ``getPending`` + an explicit ``clearPending('lvs:select')`` on deselect, in contrast to the DRC viewer which uses ``consumePending`` (only one target viewer).
* **hasListeners is a heuristic.** For top-pair selections, the LVS viewer emits to existing listeners and only requests opening new panels when no listener exists at all. Any open layout viewer counts, which is fine for the top pair (broadcast semantics) but wrong for subcircuit pairs — those always request their own (named) views and rely on ``request-open-views`` focusing already-open panels instead of duplicating them.
* **Event handlers are attached in a separate method from rendering.** The LVS viewer builds its DOM in ``update()`` but attaches handlers in ``_attachEventHandlers(itemMap, circuitMap)``; every lookup table the handlers need must be passed explicitly. A handler referencing a variable that only exists in the rendering scope fails with an *uncaught ReferenceError visible only in the browser console* — the UI just silently does nothing. When debugging "click has no effect", check the browser console first.
* **destroy() must mirror every on().** Golden Layout creates and destroys view instances as panels open and close. A view class that subscribes in its constructor must unsubscribe in ``destroy()``, otherwise stale listeners of closed panels keep reacting to events.
