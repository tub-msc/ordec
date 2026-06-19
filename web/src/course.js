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

// Probe that fetches the lesson() view through OrdecClient's existing
// one-at-a-time request queue, regardless of whether any visible result
// view shows the report. It implements the same interface as ResultViewer
// (registerClient / updateViewListAndException / requestsView / updateView)
// and is appended to the client's resultViewers list.
class ReportProbe {
    constructor(controller) {
        this.controller = controller;
        this.viewSelected = 'lesson()';
        this.viewUpToDate = false;
        this.checkRequestedByUser = false;
        this.client = null;
    }

    registerClient(client) {
        this.client = client;
    }

    updateViewListAndException() {
        this.viewUpToDate = false;
        if (this.client.exception) {
            this.controller.onReportResult({ exception: this.client.exception });
        } else if (this.autoRefreshes() || this.checkRequestedByUser) {
            this.controller.onReportPending();
        } else {
            // lesson() has auto_refresh=False (expensive checks): it is only
            // evaluated when the user clicks the Check button.
            this.controller.onReportUnchecked();
        }
    }

    requestsView() {
        if (this.viewUpToDate) {
            return false;
        }
        if (!this.client.views.has(this.viewSelected)) {
            return false;
        }
        const autoRefresh = this.client.views.get(this.viewSelected).auto_refresh;
        return autoRefresh || this.checkRequestedByUser;
    }

    autoRefreshes() {
        const info = this.client?.views?.get(this.viewSelected);
        return Boolean(info && info.auto_refresh);
    }

    // Trigger one report evaluation for lessons whose lesson() has
    // auto_refresh=False (expensive checks, e.g. LVS/DRC).
    requestCheck() {
        this.checkRequestedByUser = true;
        this.controller.onReportPending();
        this.client.requestNextView();
    }

    updateView(msg) {
        this.viewUpToDate = true;
        this.checkRequestedByUser = false;
        this.controller.onReportResult(msg);
    }
}

const STORAGE_VERSION = 1;
const PROGRESS_FORMAT = 'ordec-course-progress';

function lessonStem(file) {
    return file.replace(/\.[^.]+$/, '');
}

export class CourseController {
    constructor(course) {
        this.course = course; // {name, title, lessons: [...]} from /api/course
        this.probe = new ReportProbe(this);
        this.client = null; // set by main.js
        this.layout = null; // set by main.js
        this.editor = null; // set when the Editor component mounts
        this.navElements = []; // navigator DOM roots (re-created per Editor)
        this.reportStatus = 'busy'; // 'busy' | 'unchecked' | 'pass' | 'fail' | 'error'
        this.suspendUistateSave = false;

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

        const uistate = JSON.parse(JSON.stringify(this.lessonUistate(i)));
        uistate.header = { popout: false };

        // Editor.updateMode() takes the syntax highlighting mode from the
        // (hidden) toolbar sourcetype selector; set it before the Editor is
        // re-created by loadLayout below.
        this.deps.setSourceType(this.course.lessons[i].srctype);

        // loadLayout() recreates the Editor (incl. navigator) and all
        // ResultViewers; suspend uistate autosaving while the layout is in
        // flux.
        this.suspendUistateSave = true;
        this.editor = null;
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
        localStorage.removeItem(this.storageKey);
        window.location.reload();
    }

    // -- Navigator UI ----------------------------------------------------

    // Mounts the course navigator into nav (a div created by the Editor
    // component). Called each time an Editor is (re-)created by loadLayout.
    mountNavigator(nav, editor) {
        this.editor = editor;

        nav.classList.add('course-nav');
        nav.innerHTML = `
            <button class="toolbar-btn course-prev" title="Previous lesson"><svg class="course-arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 L5 8 L10 13"/></svg></button>
            <span class="course-nav-sep"></span>
            <select class="toolbar-btn course-lessonsel"></select>
            <span class="course-nav-sep"></span>
            <button class="toolbar-btn course-next" title="Next lesson"><svg class="course-arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3 L11 8 L6 13"/></svg></button>
            <span class="course-nav-sep"></span>
            <span class="course-marker"></span>
            <span class="course-nav-sep course-check-sep"></span>
            <button class="toolbar-btn course-check">Check</button>
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
        nav.querySelector('.course-check').onclick = () => {
            this.probe.requestCheck();
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

        // Editors are destroyed and re-created by loadLayout; drop stale
        // navigator roots.
        this.navElements = this.navElements.filter(e => e.isConnected);
        this.navElements.push(nav);
        this.renderNavigator(nav);
    }

    renderNavigators() {
        this.navElements = this.navElements.filter(e => e.isConnected);
        this.navElements.forEach(nav => this.renderNavigator(nav));
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

        // The Check button is only needed for lessons whose lesson() does
        // not auto-refresh (expensive checks). Hide its leading divider too.
        const hideCheck = this.probe.autoRefreshes();
        nav.querySelector('.course-check').style.display = hideCheck ? 'none' : '';
        nav.querySelector('.course-check-sep').style.display = hideCheck ? 'none' : '';
    }
}

// Fetches course data and creates the (singleton) CourseController.
// deps provides main.js callbacks: getResultViewers(), saveUistate(),
// registerChangeHandler(editor, client).
export async function initCourseMode(courseName, deps) {
    const params = new URLSearchParams();
    params.append('name', courseName);
    const response = await fetch('/api/course?' + params);
    if (!response.ok) {
        throw new Error(`Response status: ${response.status}`);
    }
    const course = await response.json();
    courseController = new CourseController(course);
    courseController.deps = deps;
    return courseController;
}
