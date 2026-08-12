// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// To be improved. Consider the constructor-only classes stubs for future functions.

import { LayoutGL } from './layout-gl.js';
import { HierSelector } from './hier-selector.js';
import { getCourseController, suppressCloseControls } from './course.js';
import { SvgView } from './svg-view.js';
import { ReportView } from './report-view.js';
import { DrcReport } from './drc-report.js';
import { LvsReport } from './lvs-report.js';

let idCounter = 0;
export function generateId() {
    idCounter += 1;
    return "idgen" + idCounter;
}

// Maps the type field of view messages to the class rendering that view
// type. Each class lives in its own module; ResultViewer instantiates it
// with the rescontent element and drives it via update()/destroy().
const viewClassOf = {
    svg: SvgView,
    report: ReportView,
    layout_gl: LayoutGL,
    drc_report: DrcReport,
    lvs_report: LvsReport,
}

export class ResultViewer {
    static refreshAll = false;
    static useHierSelector = true;
    // One-shot flag set by the "New Result View" toolbar button (main.js):
    // the next freshly registered viewer pops open the first dropdown of
    // its view selector, riding on the button click's user activation.
    // Never set during layout restore, where auto-opening would be wrong.
    static autoOpenPending = false;

    constructor(container, state) {
        this.container = container;
        container.element.innerHTML = `
            <div class="resview">
                <div class="resviewhead"></div>
                <div class="reswrapper">
                    <div class="refreshing"><span class="refresh-spinner" aria-hidden="true"></span><span class="refresh-status">Refreshing view…</span><span class="refresh-progress"><span class="refresh-progress-fill"></span></span><span class="refresh-pct"></span><span class="refresh-detail"></span><button class="refresh-cancel" title="Cancel view generation">✕</button></div>
                    <div class="refreshable"><button><svg class="refresh-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M13 8 A5 5 0 1 1 11.5 4.5"/><path d="M11.5 1.5 L11.5 4.5 L8.5 4.5"/></svg>Refresh</button><span class="refreshable-text">View is out of date.</span></div>
                    <div class="builderror"><span class="builderror-text"></span><button class="builderror-toggle">Show details</button></div>
                    <div class="rescontent" tabindex="1"></div>
                    <div class="resexception"></div>
                    <div class="resview-empty">Select a view from the dropdown above</div>
                </div>
            </div>
        `;
        container.addEventListener('beforeComponentRelease', () => {
            this.view?.destroy?.();
        });
        this.resizeWithContainerAutomatically = true;
        this.resOverlayRefreshing = container.element.querySelector(".refreshing");
        this.resOverlayRefreshable = container.element.querySelector(".refreshable");
        this.refreshStatus = container.element.querySelector(".refresh-status");
        this.refreshProgress = container.element.querySelector(".refresh-progress");
        this.refreshProgressFill = container.element.querySelector(".refresh-progress-fill");
        this.refreshPct = container.element.querySelector(".refresh-pct");
        this.refreshDetail = container.element.querySelector(".refresh-detail");
        this.refreshCancel = container.element.querySelector(".refresh-cancel");
        this.refreshableText = container.element.querySelector(".refreshable-text");
        this.resOverlayError = container.element.querySelector(".builderror");
        this.buildErrorText = container.element.querySelector(".builderror-text");
        this.buildErrorToggle = container.element.querySelector(".builderror-toggle");
        this.buildErrorToggle.onclick =
            () => this.setBuildErrorExpanded(!this.buildErrorExpanded);
        // Course viewer error state (see showBuildError): the full traceback
        // and whether it is expanded over the lesson report.
        this.buildError = null;
        this.buildErrorExpanded = false;
        container.element.querySelector(".refreshable button").onclick =
            () => this.refreshOnClick();
        this.refreshCancel.onclick = () => this.cancelOnClick();
        // Set when the server reports a view generation as cancelled;
        // suppresses auto-refresh until the user asks for the view again.
        this.generationCancelled = false;
        this.showRefreshOverlay(null);
        this.resContent = container.element.querySelector(".rescontent");
        this.resWrapper = container.element.querySelector(".reswrapper");
        this.resException = container.element.querySelector(".resexception");
        this.resEmpty = container.element.querySelector(".resview-empty");
        this.resViewHead = container.element.querySelector(".resviewhead");
        this.viewUpToDate = false;
        this.viewSelected = null;
        // Wire hash of the currently displayed subgraph view (wire_hash
        // field of the view message), for hash-based open dedup (see
        // main.js). Runtime state only: it must never be written into
        // componentState/uistate.
        this.wireHash = null;
        this.refreshRequestedByUser = false;
        this.directView = state && state.directView;
        // Course mode: the special "Course" panel (see course.js). It shows a
        // fixed lesson() report, hosts the course navigator toolbar in its
        // header instead of a view selector, and is titled "Course".
        this.courseMode = Boolean(state && state.course);

        if (this.courseMode) {
            this.hierSelector = null;
            this.viewSelector = null;
            this.viewSelected = (state && state.view) || 'lesson()';
            this.resEmpty.style.display = 'none';
            this.courseController = getCourseController();
            this.courseController.attachCourseViewer(this, this.resViewHead);
            this.container.setTitle('Course');
            // The Course panel must be movable but not closable.
            suppressCloseControls(this.container);
        } else if (this.directView) {
            const label = document.createElement('span');
            label.className = 'direct-view-label';
            label.textContent = state.view;
            this.resViewHead.appendChild(label);
            this.hierSelector = null;
            this.viewSelector = null;
            this.viewSelected = state.view;
            this.resEmpty.style.display = 'none';
        } else {
            this._useHier = ResultViewer.useHierSelector;
            if (this._useHier) {
                this.hierSelector = new HierSelector(this.resViewHead, {
                    onSelect: (viewName) => this._onViewSelected(viewName),
                    onDeselect: () => this._onViewDeselected(),
                });
                this.viewSelector = null;
            } else {
                this._createFlatSelector();
            }
            if (state && state['view']) {
                this.restoreSelectedView = state['view'];
            }
        }
        //this.updateGlobalState();
        this.viewListInitialized = false;
    }

    _createFlatSelector() {
        const sel = document.createElement('select');
        sel.classList.add('viewsel');
        this.resViewHead.appendChild(sel);
        this.viewSelector = sel;
        this.viewSelector.onchange = () => this.viewSelectorOnChange();
        this.hierSelector = null;
    }

    refreshOnClick() {
        this.refreshRequestedByUser = true;
        this.generationCancelled = false;
        this.showRefreshOverlay('refreshing');
        if (this.courseMode) {
            // Running the (expensive) check: reflect it in the course marker.
            this.courseController.onReportPending();
        }
        this.client.requestViews();
    }

    cancelOnClick() {
        this.refreshStatus.textContent = 'Cancelling…';
        this.refreshCancel.disabled = true;
        this.client.cancelView(this);
    }

    flashRefreshBar() {
        // Draws attention to the refresh state when the user interacts with
        // an out-of-date view (see the stale guards in the report viewers):
        // the click does nothing, and the flashing bar says why.
        const bar = [this.resOverlayRefreshing, this.resOverlayRefreshable,
            this.resOverlayError].find(el => el.style.display !== 'none');
        if (!bar) return;
        bar.classList.remove('refreshbar-flash');
        void bar.offsetWidth; // reflow, so a running animation restarts
        bar.classList.add('refreshbar-flash');
    }

    showRefreshOverlay(config) {
        this.resOverlayRefreshable.style.display = (config == 'refreshable')?'':'none';
        this.resOverlayRefreshing.style.display = (config == 'refreshing')?'':'none';
        this.resOverlayError.style.display = (config == 'error')?'':'none';
        if (config == 'refreshing') {
            // Reset progress state; updateProgress() fills it in.
            this.refreshStatus.textContent = 'Refreshing view…';
            this.refreshProgress.style.display = 'none';
            this.refreshPct.textContent = '';
            this.refreshDetail.textContent = '';
            this.refreshCancel.disabled = false;
        }
        // When a status bar is shown it occupies a fixed-height strip at the top
        // of the view; this class insets the content below it (see style.css).
        this.resOverlayRefreshing.parentElement.classList.toggle(
            'refreshbar-active',
            config == 'refreshing' || config == 'refreshable' || config == 'error');
        // Recolours the strip's top edge (the view head border) to the error
        // colour, like refreshbar-active does for the refresh colour.
        this.resOverlayRefreshing.parentElement.classList.toggle(
            'errorbar-active', config == 'error');
    }

    updateProgress(msg) {
        this.refreshStatus.textContent = msg.status;
        if (msg.fraction != null) {
            this.refreshProgress.style.display = '';
            this.refreshProgressFill.style.width = (msg.fraction * 100) + '%';
            this.refreshPct.textContent = Math.round(msg.fraction * 100) + '%';
        }
        this.refreshDetail.textContent = msg.detail ?? '';
    }

    requestsView() {
        if(!this.viewSelected) {
            return false;
        }
        if (this.generationCancelled && !this.refreshRequestedByUser) {
            // Don't auto-re-request a view the user just cancelled.
            return false;
        }
        if (this.directView) {
            return !this.viewUpToDate;
        }
        return (!this.viewUpToDate) && (
            this.refreshRequestedByUser ||
            this.viewInfo().auto_refresh ||
            ResultViewer.refreshAll
            );
    }

    viewInfo() {
        let info = this.client.views.get(this.viewSelected);
        if(info) {
            return info;
        } else {
            return {};
        }
    }

    resetResContent() {
        // Replace the rescontent div with a fresh rescontent div, mainly
        // to clear any event handlers that might have been attached to the
        // resContent previously.
        const resContentNew = document.createElement('div');
        resContentNew.classList.add('rescontent');
        resContentNew.tabIndex = "0";
        this.resWrapper.replaceChild(resContentNew, this.resContent);
        this.resContent = resContentNew;
    }

    viewSelectorOnChange() {
        const viewName = this.viewSelector.options[this.viewSelector.selectedIndex].value;
        this._onViewSelected(viewName);
    }

    _onViewSelected(viewName) {
        this.viewSelected = viewName;
        this.container.setState({ view: viewName });
        this.container.setTitle(viewName);
        this.resEmpty.style.display = 'none';

        this.invalidate();
        this.resetResContent();
        this.resContent.focus();
        this.view?.destroy?.();
        this.view = null;
        this.client.requestViews();
    }

    _onViewDeselected() {
        this.viewSelected = null;
        this.viewUpToDate = false;
        this.view?.destroy?.();
        this.view = null;
        this.container.setTitle('Result View');
        this.showRefreshOverlay(null);
        this.showException(null);
        this.resetResContent();
        this.resEmpty.style.display = '';
    }

    invalidate() {
        this.viewUpToDate = false;
        this.refreshRequestedByUser = false;
        this.generationCancelled = false;

        this.updateOverlay();
    }

    updateOverlay() {
        if((!this.viewSelected) || this.viewUpToDate) {
            this.showRefreshOverlay(null);
        } else if(this.generationCancelled) {
            this.refreshableText.textContent = 'View generation cancelled.';
            this.showRefreshOverlay("refreshable");
        } else if(this.viewInfo().auto_refresh && !ResultViewer.refreshAll) {
            this.showRefreshOverlay("refreshing");
        } else {
            this.refreshableText.textContent = 'View is out of date.';
            this.showRefreshOverlay("refreshable");
        }
    }

    updateViewList(freshViewlist = false) {
        if (this.courseMode) {
            // Fixed lesson() view, no selector; the navigator toolbar lives in
            // the header and the title stays "Course".
            this.container.setTitle('Course');
            this.viewListInitialized = true;
            return;
        }

        if (this.directView) {
            this.container.setTitle(this.viewSelected);
            this.viewListInitialized = true;
            return;
        }

        // Check if mode toggled at runtime
        if (this._useHier !== ResultViewer.useHierSelector) {
            this._useHier = ResultViewer.useHierSelector;
            this.resViewHead.replaceChildren();
            if (this._useHier) {
                this.viewSelector = null;
                this.hierSelector = new HierSelector(this.resViewHead, {
                    onSelect: (viewName) => this._onViewSelected(viewName),
                });
            } else {
                this.hierSelector = null;
                this._createFlatSelector();
            }
        }

        // In course mode, the lesson() report is shown by the Course panel;
        // hide it from the view selectors of the regular result viewers.
        const hideLesson = Boolean(getCourseController());
        const viewNames = [];
        this.client.views.forEach(view => {
            if (hideLesson && view.name === 'lesson()') {
                return;
            }
            viewNames.push(view.name);
        });

        const prevSelected = this.viewSelected || this.restoreSelectedView;

        if (this._useHier) {
            this.hierSelector.update(viewNames, prevSelected);
            this.viewSelected = this.hierSelector.selectedView;
            // Consume the one-shot auto-open on the first list update of a
            // freshly created, still-unselected viewer (viewListInitialized
            // discriminates it from older viewers left unselected, which
            // are also updated by the same stateChanged event).
            if (ResultViewer.autoOpenPending && !this.viewListInitialized
                    && !this.viewSelected) {
                ResultViewer.autoOpenPending = false;
                this.hierSelector.openFirst();
            }
        } else {
            let vs = this.viewSelector;
            vs.innerHTML = "<option disabled selected value>--- Select result from list ---</option>";
            let selectedVal = null;
            viewNames.forEach(name => {
                var option = document.createElement("option");
                option.innerText = name;
                option.value = name;
                vs.appendChild(option);
                if (name == prevSelected) {
                    option.selected = true;
                    selectedVal = name;
                }
            });
            this.viewSelected = selectedVal;
        }
        if (this.viewSelected) {
            this.container.setTitle(this.viewSelected);
            this.resEmpty.style.display = 'none';
        } else if (prevSelected && freshViewlist) {
            // The previously selected view no longer exists in the fresh
            // view list (e.g. its cell was renamed or removed in the
            // sources): fully deselect so the stale render does not linger
            // behind the "Select a view" placeholder. Only done for fresh
            // viewlist messages: during viewer registration or a module
            // build exception the list is stale or not yet loaded and the
            // selection must be kept for a later restore.
            this.restoreSelectedView = null;
            this.container.setState({ view: null });
            this._onViewDeselected();
        }
        this.viewListInitialized = true;
    }

    updateViewListAndException(freshViewlist = false) {
        this.updateViewList(freshViewlist);
        if (this.client.exception) {
            // In this case, the exception was generated during module evaluation:
            if (this.courseMode) {
                this.showBuildError(this.client.exception);
            } else {
                this.showRefreshOverlay(null);
                this.showException(this.client.exception);
            }
        } else {
            this.clearBuildError();
            this.showException(null);
            this.invalidate();
            this.updateOverlay();
        }
        if (this.courseMode) {
            this._notifyCourseStatus();
        }
    }

    // Reflect the post-build state of the lesson() view in the course marker:
    // an error from the build, a pending check (auto-refresh or Check just
    // clicked), or an unchecked state awaiting the Check button.
    _notifyCourseStatus() {
        if (this.client.exception) {
            this.courseController.onReportResult({ exception: this.client.exception });
        } else if (this.requestsView()) {
            this.courseController.onReportPending();
        } else {
            // The lesson() view is not being requested. This happens when it
            // was declared with @generate_func(auto_refresh=False) (expensive
            // checks, e.g. LVS/DRC) and is evaluated only when the user
            // clicks the in-panel Refresh overlay; the marker reflects this
            // "not checked" state. Plain @generate_func lessons auto-refresh
            // and never end up here.
            this.courseController.onReportUnchecked();
        }
    }

    registerClient(client) {
        this.client = client;
        this.updateViewList();
    }

    showException(text) {
        this.resException.style.display = text?'':'none';
        this.resContent.style.display = text?'none':'';
        this.resEmpty.style.display = (text || this.viewSelected) ? 'none' : '';

        if(text) {
            let pre = document.createElement("pre");
            pre.innerText = text;
            pre.classList.add('exception');
            this.resException.replaceChildren(pre);
        }
    }

    // Course viewer only: non-destructive error display. A build or check
    // error must not wipe the lesson() report the student is following (the
    // common case is a transient syntax error while typing), so the last good
    // report stays visible and the error appears as a strip; the full
    // traceback expands over the report on demand.
    showBuildError(text) {
        this.buildError = text;
        // Summary for the strip: the traceback's exception line, e.g.
        // "SyntaxError: invalid syntax (<webeditor>, line 12)". Usually the
        // last line, but exceptions with multi-line messages (e.g. ORD syntax
        // errors) have the message's remaining lines after it, so search for
        // the last line that looks like an exception line.
        const lines = text.trim().split('\n');
        const summary = lines.findLast(
            l => /^[A-Za-z_][\w.]*(Error|Exception)\b/.test(l));
        this.buildErrorText.textContent = summary || lines[lines.length - 1];
        this.showRefreshOverlay('error');
        // Keep the details open across consecutive failed builds. With no
        // previously rendered report there is nothing to preserve, so open
        // them right away.
        this.setBuildErrorExpanded(this.buildErrorExpanded || !this.view);
    }

    setBuildErrorExpanded(expanded) {
        this.buildErrorExpanded = expanded;
        this.buildErrorToggle.textContent =
            expanded ? 'Hide details' : 'Show details';
        this.showException(expanded ? this.buildError : null);
    }

    clearBuildError() {
        if (this.buildError !== null) {
            this.buildError = null;
            this.setBuildErrorExpanded(false);
        }
    }

    updateView(msg) {
        if (msg.cancelled) {
            // Terminal state of a cancelled generation: the view stays out
            // of date, but is not re-requested until the user asks for it
            // (via the Refresh button of the overlay shown here).
            this.viewUpToDate = false;
            this.refreshRequestedByUser = false;
            this.generationCancelled = true;
            this.updateOverlay();
            if (this.courseMode) {
                this.courseController.onReportUnchecked();
            }
            return;
        }

        //this.resContent.replaceChildren();
        this.viewUpToDate = true;
        this.wireHash = msg.exception ? null : (msg.wire_hash || null);
        this.showRefreshOverlay(null);

        try {
            if(msg.exception) {
                // In this case, the exception was generated during view generation:
                if (this.courseMode) {
                    // Shows the error strip; updateOverlay() must not run
                    // here, it would hide the strip again (view up to date).
                    this.showBuildError(msg.exception);
                } else {
                    this.showException(msg.exception);
                    this.updateOverlay();
                }
            } else {
                this.clearBuildError();
                this.showException(null);
                const viewClass = viewClassOf[msg.type];
                if(!viewClass) {
                    let pre = document.createElement("pre");
                    pre.innerText = 'no handler found for type ' + msg.type;
                    this.resContent.replaceChildren(pre);
                } else if(this.view instanceof viewClass) {
                    this.view.wireHash = this.wireHash;
                    this.view.resultViewer = this;
                    this.view.update(msg.data);
                } else {
                    this.view = new viewClass(this.resContent);
                    this.view.viewName = this.viewSelected;
                    this.view.wireHash = this.wireHash;
                    this.view.resultViewer = this;
                    this.view.glContainer = this.container;
                    this.view.update(msg.data);
                }
                this.updateOverlay();
            }
        } finally {
            if (this.courseMode) {
                // Feed the result (pass/fail elements) back to the course
                // controller for the marker and lesson gating, even if
                // rendering threw: the report data is valid regardless of a
                // render glitch (e.g. a plot failing to lay out in a headless
                // browser).
                this.courseController.onReportResult(msg);
            }
        }
    }

    testInfo() {
        // For automated browser testing (see test_web.py).
        const r = this.resContent.getBoundingClientRect();
        return {
            html: this.resContent.innerHTML,
            top: r.top,
            right: r.right,
            bottom: r.bottom,
            left: r.left,
            width: r.width,
            height: r.height,
        };
    }
}
