// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// The spotlight intro tour of the course mode's welcome lesson: the step
// definitions for the generic Spotlight component (see spotlight.js).
// Started by CourseController on every visit of the welcome lesson.

import { Spotlight } from './spotlight.js';

// controller is the CourseController (used to locate the Course panel and
// the result viewers); onDone fires when the tour ends via Done or Skip.
export function startCourseTour(controller, onDone) {
    // The stack (tab bar + content) of the first regular result viewer,
    // e.g. the pre-opened schematic viewer of the welcome lesson.
    const resViewerStack = () => {
        const rv = controller.deps.getResultViewers().find(v => !v.courseMode);
        return rv ? rv.container.element.closest('.lm_stack') : null;
    };
    const spotlight = new Spotlight([
        {
            target: () => controller.courseViewer?.container.element
                .closest('.lm_stack'),
            title: 'Course panel',
            text: 'This panel contains your instructions and tracks your progress for each lesson of the course.',
        },
        {
            target: () => document.querySelector('.ace_editor')
                ?.closest('.lm_stack'),
            title: 'Source editor',
            text: 'This is the source code editor. Most lessons are solved by editing it, and changes are checked as you type.',
        },
        {
            target: resViewerStack,
            title: 'Result viewer',
            text: 'This panel shows one view of the design. In this case it is the schematic of the welcome circuit. Result viewers can be dragged around and arranged in different configurations, including on top of each other as tabs.',
        },
        {
            target: () => resViewerStack()?.querySelector('.lm_controls .lm_maximise'),
            title: 'Maximize',
            text: 'This button expands this result viewer to the full window. Pressing it again restores the layout.',
        },
        {
            target: () => resViewerStack()?.querySelector('.lm_header .lm_close_tab'),
            title: 'Close',
            text: 'This button closes this result viewer. Any view can be reopened in a new result viewer at any time.',
        },
        {
            target: () => document.querySelector('#newresview'),
            title: 'New result view',
            text: 'This button opens a new result viewer panel, in which you can pick any view of the design. You will need this in the next lesson.',
        },
        {
            target: () => [
                document.querySelector('#autoRefreshToggle'),
                document.querySelector('#refresh'),
            ],
            title: 'Refreshing views',
            text: 'With auto-refresh on, all views update as you type. When off, you must press the "Refresh" button manually.',
        },
        {
            target: () => document.querySelector('#examples'),
            title: 'Examples',
            text: 'This button takes you back to the ORDeC overview page where you can select different examples, courses or start with a blank ORD file.',
        },
        {
            target: () => document.querySelector('#docs'),
            title: 'Documentation',
            text: 'This link opens the ORDeC documentation for the installed version in a new tab.',
        },
        {
            target: () => document.querySelector('#status'),
            title: 'Status indicator',
            text: 'Right now the indicator should say "ready". It shows you whether the ORDeC backend is busy generating views, whether an error occured or whether the backend is disconnected.',
        },
        {
            target: () => ['.course-prev', '.course-lessonsel',
                '.course-next'].map(sel => controller.courseViewer?.resViewHead
                    ?.querySelector(sel)),
            title: 'Lesson selector',
            text: 'Switch between lessons with the arrows or the dropdown. Later lessons unlock as you solve the ones before them.',
        },
        {
            target: () => controller.courseViewer?.resViewHead?.querySelector('.course-marker'),
            title: 'Lesson status',
            text: 'This shows whether the current lesson is solved.',
        },
        {
            target: () => ['.course-export', '.course-import', '.course-startover'].map(
                sel => controller.courseViewer?.resViewHead?.querySelector(sel)),
            title: 'Course progress',
            text: 'Your course progress is saved in the browser. Moreover, you can "Export" your progress and source code as a zip file and later "Import" it back. To reset your course progress, press "Start over".',
        },
    ], onDone);
    spotlight.start();
}
