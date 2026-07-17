// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Course mode: game-like progression through an ordered list of lesson
// source files. Each lesson has a lesson() view (synthesized server-side from
// the course manifest, see server.py) whose passfail elements decide whether
// the lesson is passed; lesson n+1 unlocks once lesson n has passed. See
// CourseController below for the navigator UI and persistence.

import { zipSync, unzipSync, strToU8, strFromU8 } from 'fflate';

let courseController = null;

export function getCourseController() {
    return courseController;
}

// Make a GoldenLayout panel movable but not closable. GoldenLayout couples the
// two (a non-closable tab cannot be dragged out of its stack, see
// Header._canRemoveComponent), so the panel is left closable and its close
// controls are hidden instead: the tab's own close button, and the close button
// of the header of whatever stack currently holds it (which removes the whole
// stack). Re-applied on every 'tab' event, as the tab and its header are
// re-created when the panel is moved; deferred to a microtask because the tab
// is not yet attached to its header's DOM when 'tab' fires.
export function suppressCloseControls(container) {
    let lockedHeader = null;
    const apply = (tab) => {
        queueMicrotask(() => {
            if (lockedHeader) {
                lockedHeader.classList.remove('panel-locked-header');
                lockedHeader = null;
            }
            if (!tab || !tab.element.isConnected) {
                return;
            }
            tab.element.classList.add('panel-locked-tab');
            const header = tab.element.closest('.lm_header');
            if (header) {
                header.classList.add('panel-locked-header');
                lockedHeader = header;
            }
        });
    };
    container.on('tab', apply);
    apply(container.tab);
}

const STORAGE_VERSION = 1;
const PROGRESS_FORMAT = 'ordec-course-progress';

function lessonStem(file) {
    return file.replace(/\.[^.]+$/, '');
}

export class CourseController {
    constructor(course) {
        this.course = course; // {name, title, lessons: [...]} from /api/course
        this.client = null; // set by main.js
        this.layout = null; // set by main.js
        this.editor = null; // set when the Editor component mounts
        // The special "Course" result viewer that renders lesson() and hosts
        // the navigator toolbar (see resultviewer.js course mode); set when
        // that viewer mounts.
        this.courseViewer = null;
        this.navElements = []; // navigator DOM roots (re-created per Editor)
        this.reportStatus = 'busy'; // 'busy' | 'unchecked' | 'pass' | 'fail' | 'error'
        this.suspendUistateSave = false;
        // Callout shown over the lesson report: null | 'intro' | 'success'.
        this.calloutKind = null;
        // Both callouts' dismissals are per visit (in-memory): they are reset
        // on every lesson (re)activation, so a callout reappears when its lesson
        // is revisited.
        this.introDismissed = false;
        this.successDismissed = false;

        this.state = this.loadState();
    }

    // -- Persistence (localStorage) ---------------------------------

    get storageKey() {
        return 'ordecCourse:' + this.course.name;
    }

    loadState() {
        let state = null;
        try {
            state = JSON.parse(localStorage.getItem(this.storageKey));
        } catch (e) {
            console.error('Failed to parse course state, starting fresh:', e);
        }
        if (!state || state.version !== STORAGE_VERSION) {
            state = { version: STORAGE_VERSION, currentLesson: 0, lessons: {} };
        }
        if (typeof state.currentLesson !== 'number'
            || state.currentLesson < 0
            || state.currentLesson >= this.course.lessons.length) {
            state.currentLesson = 0;
        }
        return state;
    }

    saveState() {
        localStorage.setItem(this.storageKey, JSON.stringify(this.state));
    }

    lessonState(i) {
        const stem = lessonStem(this.course.lessons[i].file);
        if (!this.state.lessons[stem]) {
            this.state.lessons[stem] = {};
        }
        return this.state.lessons[stem];
    }

    // -- Lesson accessors --------------------------------------------

    get currentLesson() {
        return this.state.currentLesson;
    }

    lessonSrc(i) {
        const saved = this.lessonState(i).src;
        return (saved !== undefined) ? saved : this.course.lessons[i].src;
    }

    lessonUistate(i) {
        return this.lessonState(i).uistate || this.course.lessons[i].uistate;
    }

    lessonPassed(i) {
        // "Ever passed" - used for gating, so later edits do not re-lock
        // already unlocked lessons.
        return Boolean(this.lessonState(i).passed);
    }

    lessonUnlocked(i) {
        // In debug mode (debug=true in the URL fragment), every lesson is
        // accessible regardless of progress.
        if (this.deps && this.deps.debug) {
            return true;
        }
        return (i === 0) || this.lessonPassed(i - 1);
    }

    // -- Lesson switching ---------------------------------------------

    // Saves the current lesson's state (unless save=false) and rebuilds
    // editor + viewers for lesson i. Mirrors the integrated-mode init
    // sequence in main.js.
    activateLesson(i, { save = true } = {}) {
        if (save) {
            this.saveCurrentLesson();
        }
        this.state.currentLesson = i;
        this.saveState();
        this.reportStatus = 'busy';
        this.introDismissed = false;
        this.successDismissed = false;

        const uistate = JSON.parse(JSON.stringify(this.lessonUistate(i)));
        uistate.header = { popout: false };

        // Editor.updateMode() takes the syntax highlighting mode from the
        // (hidden) toolbar sourcetype selector; set it before the Editor is
        // re-created by loadLayout below.
        this.deps.setSourceType(this.course.lessons[i].srctype);

        // loadLayout() recreates the Editor and all ResultViewers (including
        // the Course viewer that hosts the navigator); they re-register
        // themselves via setEditor/attachCourseViewer. Suspend uistate
        // autosaving while the layout is in flux.
        this.suspendUistateSave = true;
        this.editor = null;
        this.courseViewer = null;
        this.layout.loadLayout(uistate);
        this.suspendUistateSave = false;

        const src = this.lessonSrc(i);
        this.client.srctype = this.course.lessons[i].srctype;
        this.client.src = src;
        // Check epilogue, executed server-side after the lesson source to
        // define the lesson() view (see server.py lesson_check_src).
        this.client.checkSrc = this.course.lessons[i].check_src;
        if (this.editor) {
            this.editor.loadSrc(src);
        }
        this.client.registerResultViewers(this.deps.getResultViewers());
        this.client.connect();
        if (this.editor) {
            this.deps.registerChangeHandler(this.editor, this.client);
        }
        this.renderNavigators();
    }

    saveCurrentLesson() {
        const ls = this.lessonState(this.state.currentLesson);
        if (this.editor) {
            ls.src = this.editor.editor.getValue();
        }
        ls.uistate = this.deps.saveUistate();
        this.saveState();
    }

    // Called (debounced via Editor's change handler) on source edits.
    autosaveSrc(src) {
        this.lessonState(this.state.currentLesson).src = src;
        this.saveState();
    }

    // Called on GoldenLayout stateChanged events.
    uistateChanged() {
        if (this.suspendUistateSave) {
            return;
        }
        window.clearTimeout(this.uistateSaveTimeout);
        this.uistateSaveTimeout = window.setTimeout(() => {
            if (this.suspendUistateSave) {
                return;
            }
            this.lessonState(this.state.currentLesson).uistate =
                this.deps.saveUistate();
            this.saveState();
        }, 500);
    }

    // -- Report evaluation ---------------------------------------------

    onReportPending() {
        this.reportStatus = 'busy';
        this.renderNavigators();
    }

    onReportUnchecked() {
        this.reportStatus = 'unchecked';
        this.renderNavigators();
    }

    onReportResult(msg) {
        if (msg.exception) {
            this.reportStatus = 'error';
        } else if (msg.type === 'report') {
            const passfails = (msg.data.elements || [])
                .filter(e => e.element_type === 'passfail');
            const passed = (passfails.length > 0)
                && passfails.every(e => e.passed);
            this.reportStatus = passed ? 'pass' : 'fail';
            if (passed && !this.lessonPassed(this.state.currentLesson)) {
                this.lessonState(this.state.currentLesson).passed = true;
                this.saveState();
            }
        } else {
            console.error('course: unexpected report view type', msg.type);
            this.reportStatus = 'error';
        }
        this.renderNavigators();
    }

    // -- Zip import/export ----------------------------------------------

    exportZip() {
        this.saveCurrentLesson();
        const files = {};
        const passed = {};
        this.course.lessons.forEach((lesson, i) => {
            files[lesson.file] = strToU8(this.lessonSrc(i));
            const ls = this.lessonState(i);
            if (ls.uistate) {
                files[lessonStem(lesson.file) + '.uistate.json'] =
                    strToU8(JSON.stringify(ls.uistate));
            }
            passed[lessonStem(lesson.file)] = this.lessonPassed(i);
        });
        files['progress.json'] = strToU8(JSON.stringify({
            format: PROGRESS_FORMAT,
            version: STORAGE_VERSION,
            course: this.course.name,
            currentLesson: this.state.currentLesson,
            passed: passed,
        }, null, 2));

        const zipped = zipSync(files);
        const blob = new Blob([zipped], { type: 'application/zip' });
        const url = URL.createObjectURL(blob);
        const dlAnchorElem = document.querySelector('#downloadAnchorElem');
        dlAnchorElem.setAttribute('href', url);
        dlAnchorElem.setAttribute('download',
            'ordec-course-' + this.course.name + '.zip');
        dlAnchorElem.click();
        URL.revokeObjectURL(url);
    }

    importZip(arrayBuffer) {
        let files;
        try {
            files = unzipSync(new Uint8Array(arrayBuffer));
        } catch (e) {
            alert('Could not read zip file: ' + e);
            return;
        }
        if (!files['progress.json']) {
            alert('Not a course progress zip (progress.json missing).');
            return;
        }
        let progress;
        try {
            progress = JSON.parse(strFromU8(files['progress.json']));
        } catch (e) {
            alert('Could not parse progress.json: ' + e);
            return;
        }
        if (progress.format !== PROGRESS_FORMAT) {
            alert('Not a course progress zip (unexpected format).');
            return;
        }
        if (progress.course !== this.course.name) {
            alert('This zip belongs to course ' + JSON.stringify(progress.course)
                + ', not to the current course '
                + JSON.stringify(this.course.name) + '.');
            return;
        }

        const state = {
            version: STORAGE_VERSION,
            currentLesson: 0,
            lessons: {},
        };
        this.course.lessons.forEach((lesson, i) => {
            const stem = lessonStem(lesson.file);
            const ls = {};
            if (files[lesson.file]) {
                ls.src = strFromU8(files[lesson.file]);
            }
            if (files[stem + '.uistate.json']) {
                try {
                    ls.uistate = JSON.parse(strFromU8(files[stem + '.uistate.json']));
                } catch (e) {
                    console.error('Ignoring broken uistate for', stem, e);
                }
            }
            if (progress.passed && progress.passed[stem]) {
                ls.passed = true;
            }
            state.lessons[stem] = ls;
        });
        if (typeof progress.currentLesson === 'number'
            && progress.currentLesson >= 0
            && progress.currentLesson < this.course.lessons.length) {
            state.currentLesson = progress.currentLesson;
        }
        localStorage.setItem(this.storageKey, JSON.stringify(state));
        window.location.reload();
    }

    startOver() {
        if (!window.confirm('Start over? All your course progress and edits '
            + 'will be lost.')) {
            return;
        }
        // Cancel any pending debounced uistate save so it cannot re-create the
        // storage entry between removeItem and the reload completing.
        this.suspendUistateSave = true;
        window.clearTimeout(this.uistateSaveTimeout);
        localStorage.removeItem(this.storageKey);
        window.location.reload();
    }

    // -- Component registration ------------------------------------------

    // The Editor component registers itself here when it mounts, so the
    // controller can read/replace the editor source on lesson switches.
    setEditor(editor) {
        this.editor = editor;
    }

    // The special "Course" result viewer (resultviewer.js course mode)
    // registers itself here and provides its header element as the host for
    // the navigator toolbar.
    attachCourseViewer(viewer, navEl) {
        this.courseViewer = viewer;
        this.mountNavigator(navEl);
        this.updateCallout();
    }

    // -- Callout over the lesson report ----------------------------------
    //
    // A hint floating over the top of the lesson report. The report renderer
    // owns rescontent and replaces its children on every refresh, so the
    // callout lives in the surrounding reswrapper instead, with an arrow
    // pointing up into the header. Two kinds:
    //   'intro'   - red, shown until the lesson passes: edit the source below
    //               until all checks pass; arrow points at the status marker.
    //   'success' - green, shown once the lesson passes: press the next arrow
    //               to continue (or, on the last lesson, a closing note with no
    //               arrow); replaces the intro callout.
    // Both callouts are dismissable for the current visit only and reappear
    // when their lesson is revisited (see introDismissed/successDismissed).

    desiredCalloutKind() {
        if (this.reportStatus === 'pass') {
            return this.successDismissed ? null : 'success';
        }
        // The intro hint explains the course mechanics, so it is only shown on
        // the first lesson, until dismissed.
        if (this.state.currentLesson === 0 && !this.introDismissed) {
            return 'intro';
        }
        return null;
    }

    // Reconciles the displayed callout with desiredCalloutKind(): rebuilds it
    // when the kind changed, otherwise just re-aligns it. Called whenever the
    // report status or navigator changes.
    updateCallout() {
        if (!this.courseViewer) {
            return;
        }
        const desired = this.desiredCalloutKind();
        if (desired === this.calloutKind) {
            this.alignCallout();
            return;
        }
        this.removeCallout();
        if (desired) {
            this.buildCallout(desired);
        }
    }

    buildCallout(kind) {
        const viewer = this.courseViewer;
        const isLast =
            this.state.currentLesson === this.course.lessons.length - 1;
        // The success callout's arrow points at the next-lesson button, which
        // does not exist on the last lesson.
        const showArrow = (kind !== 'success') || !isLast;

        let text;
        if (kind === 'success' && isLast) {
            text = `<strong>Lesson completed!</strong>
                <p>Well done &mdash; all checks pass. This was the last lesson
                of the course.</p>`;
        } else if (kind === 'success') {
            text = `<strong>Lesson completed!</strong>
                <p>All checks pass. Press the <em>next</em> arrow above to
                continue with the next lesson.</p>`;
        } else {
            text = `<strong>How this lesson works</strong>
                <p>Edit the source code in the editor below until every check
                passes. The status indicator above shows <em>unsolved</em> for
                now &mdash; once you have completed all tasks of this lesson, it
                will turn into <em>solved</em>.</p>`;
        }

        const callout = document.createElement('div');
        callout.className = 'course-callout course-callout-' + kind;
        callout.innerHTML = `
            ${showArrow ? '<div class="course-callout-arrow"></div>' : ''}
            <button class="course-callout-close" title="Hide this hint" aria-label="Hide this hint">&times;</button>
            <div class="course-callout-text">${text}</div>
        `;
        callout.querySelector('.course-callout-close').onclick =
            () => this.dismissCallout();
        viewer.resWrapper.appendChild(callout);
        this.calloutEl = callout;
        this.calloutKind = kind;

        // Keep the reserved space and the arrow position in sync as the panel
        // (and hence the target button position and the callout's wrapped
        // height) change size.
        this.calloutObserver = new ResizeObserver(() => this.alignCallout());
        this.calloutObserver.observe(viewer.resWrapper);
        this.calloutObserver.observe(callout);
        this.alignCallout();
    }

    removeCallout() {
        if (this.calloutObserver) {
            this.calloutObserver.disconnect();
            this.calloutObserver = null;
        }
        if (this.calloutEl) {
            this.calloutEl.remove();
            this.calloutEl = null;
        }
        this.calloutKind = null;
        if (this.courseViewer) {
            this.courseViewer.resContent.style.paddingTop = '';
        }
    }

    dismissCallout() {
        if (this.calloutKind === 'success') {
            this.successDismissed = true;
        } else {
            this.introDismissed = true;
        }
        this.removeCallout();
    }

    alignCallout() {
        const callout = this.calloutEl;
        const viewer = this.courseViewer;
        if (!callout || !viewer) {
            return;
        }
        // Reserve space at the top of the scrollable report so the floating
        // callout does not cover the lesson heading.
        viewer.resContent.style.paddingTop = callout.offsetHeight + 'px';
        const arrow = callout.querySelector('.course-callout-arrow');
        if (!arrow) {
            return;
        }
        // Point the arrow up at the marker (intro) or the next button (success).
        const targetSel = (this.calloutKind === 'success')
            ? '.course-next' : '.course-marker';
        const target = viewer.resViewHead.querySelector(targetSel);
        if (target) {
            const wrapRect = viewer.resWrapper.getBoundingClientRect();
            const tRect = target.getBoundingClientRect();
            const center = tRect.left + tRect.width / 2 - wrapRect.left;
            arrow.style.left = center + 'px';
        }
    }

    // -- Navigator UI ----------------------------------------------------

    // Mounts the course navigator into nav (the header element of the Course
    // result viewer). Called each time that viewer is (re-)created by
    // loadLayout.
    mountNavigator(nav) {
        nav.classList.add('course-nav');
        nav.innerHTML = `
            <button class="toolbar-btn course-prev" title="Previous lesson"><svg class="course-arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 L5 8 L10 13"/></svg></button>
            <span class="course-nav-sep"></span>
            <select class="toolbar-btn course-lessonsel"></select>
            <span class="course-nav-sep"></span>
            <button class="toolbar-btn course-next" title="Next lesson"><svg class="course-arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3 L11 8 L6 13"/></svg></button>
            <span class="course-nav-sep"></span>
            <span class="course-marker"></span>
            <span class="course-nav-spacer"></span>
            <span class="course-nav-sep"></span>
            <button class="toolbar-btn course-export" title="Download all lesson sources and progress as zip">Export</button>
            <span class="course-nav-sep"></span>
            <button class="toolbar-btn course-import" title="Restore lesson sources and progress from zip">Import</button>
            <span class="course-nav-sep"></span>
            <button class="toolbar-btn course-startover">Start over</button>
            <input type="file" class="course-import-file" accept=".zip" style="display:none">
        `;

        nav.querySelector('.course-prev').onclick = () => {
            const i = this.state.currentLesson - 1;
            if (i >= 0) {
                this.activateLesson(i);
            }
        };
        nav.querySelector('.course-next').onclick = () => {
            const i = this.state.currentLesson + 1;
            if (i < this.course.lessons.length && this.lessonUnlocked(i)) {
                this.activateLesson(i);
            }
        };
        nav.querySelector('.course-lessonsel').onchange = (ev) => {
            this.activateLesson(parseInt(ev.target.value, 10));
        };
        nav.querySelector('.course-export').onclick = () => this.exportZip();
        const fileInput = nav.querySelector('.course-import-file');
        nav.querySelector('.course-import').onclick = () => fileInput.click();
        fileInput.onchange = async () => {
            if (fileInput.files.length > 0) {
                this.importZip(await fileInput.files[0].arrayBuffer());
            }
        };
        nav.querySelector('.course-startover').onclick = () => this.startOver();

        // The Course viewer is destroyed and re-created by loadLayout; drop
        // stale navigator roots.
        this.navElements = this.navElements.filter(e => e.isConnected);
        this.navElements.push(nav);
        this.renderNavigator(nav);
    }

    renderNavigators() {
        this.navElements = this.navElements.filter(e => e.isConnected);
        this.navElements.forEach(nav => this.renderNavigator(nav));
        this.updateCallout();
    }

    renderNavigator(nav) {
        const cur = this.state.currentLesson;

        const sel = nav.querySelector('.course-lessonsel');
        sel.replaceChildren();
        this.course.lessons.forEach((lesson, i) => {
            const option = document.createElement('option');
            const unlocked = this.lessonUnlocked(i);
            option.value = i;
            option.innerText = (i + 1) + ': ' + lesson.title;
            option.title = lesson.description || '';
            option.disabled = !unlocked;
            option.selected = (i === cur);
            sel.appendChild(option);
        });

        nav.querySelector('.course-prev').disabled = (cur <= 0);
        nav.querySelector('.course-next').disabled =
            (cur + 1 >= this.course.lessons.length)
            || !this.lessonUnlocked(cur + 1);

        const marker = nav.querySelector('.course-marker');
        marker.className = 'course-marker course-marker-' + this.reportStatus;
        marker.innerText = {
            busy: 'checking…',
            unchecked: 'not checked',
            pass: 'solved',
            fail: 'unsolved',
            error: 'check error',
        }[this.reportStatus];
        marker.title = (this.reportStatus === 'error')
            ? 'The lesson source or its checks raised an exception. See the '
                + 'report view for details.'
            : 'Lesson check status. See the report view for details.';
    }
}

// Fetches course data and creates the (singleton) CourseController.
// deps provides main.js callbacks: getResultViewers(), saveUistate(),
// registerChangeHandler(editor, client).
export async function initCourseMode(courseName, deps) {
    const params = new URLSearchParams();
    params.append('name', courseName);
    const response = await fetch('api/course?' + params);
    if (!response.ok) {
        throw new Error(`Response status: ${response.status}`);
    }
    const course = await response.json();
    courseController = new CourseController(course);
    courseController.deps = deps;
    return courseController;
}
