// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Import both Golden Layout themes. Only one will be active at a time;
// the inactive one is disabled via its stylesheet's .disabled property.
import goldenLayoutLightCssUrl from "golden-layout/dist/css/themes/goldenlayout-light-theme.css?url";
import goldenLayoutDarkCssUrl from "golden-layout/dist/css/themes/goldenlayout-dark-theme.css?url";

const STORAGE_KEY = 'ordecTheme';

let goldenLayoutLightLink = null;
let goldenLayoutDarkLink = null;
let aceEditors = [];

function createGoldenLayoutLinks(dark) {
    goldenLayoutLightLink = document.createElement('link');
    goldenLayoutLightLink.rel = 'stylesheet';
    goldenLayoutLightLink.href = goldenLayoutLightCssUrl;
    goldenLayoutLightLink.disabled = dark;
    document.head.appendChild(goldenLayoutLightLink);

    goldenLayoutDarkLink = document.createElement('link');
    goldenLayoutDarkLink.rel = 'stylesheet';
    goldenLayoutDarkLink.href = goldenLayoutDarkCssUrl;
    goldenLayoutDarkLink.disabled = !dark;
    document.head.appendChild(goldenLayoutDarkLink);
}

export function isDark() {
    return document.body.classList.contains('theme-dark');
}

function applyTheme(dark) {
    if (dark) {
        document.body.classList.add('theme-dark');
    } else {
        document.body.classList.remove('theme-dark');
    }

    if (goldenLayoutLightLink && goldenLayoutDarkLink) {
        goldenLayoutLightLink.disabled = dark;
        goldenLayoutDarkLink.disabled = !dark;
    }

    const aceTheme = dark ? "ace/theme/github_dark" : "ace/theme/github";
    for (const editor of aceEditors) {
        editor.setTheme(aceTheme);
    }

    const btn = document.querySelector('#theme-toggle');
    if (btn) {
        btn.textContent = dark ? '\u2600' : '\u263E';
        btn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
    }
}

export function registerAceEditor(editor) {
    aceEditors.push(editor);
    editor.setTheme(isDark() ? "ace/theme/github_dark" : "ace/theme/github");
}

// Must be called when an editor is destroyed (see Editor in main.js):
// applyTheme() would otherwise keep setting the theme on dead instances,
// and the array would grow with every lesson switch.
export function unregisterAceEditor(editor) {
    const i = aceEditors.indexOf(editor);
    if (i >= 0) {
        aceEditors.splice(i, 1);
    }
}

export function initTheme() {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    const dark = saved === 'dark';
    createGoldenLayoutLinks(dark);
    applyTheme(dark);

    const btn = document.querySelector('#theme-toggle');
    if (btn) {
        btn.addEventListener('click', () => {
            const nowDark = !isDark();
            applyTheme(nowDark);
            window.localStorage.setItem(STORAGE_KEY, nowDark ? 'dark' : 'light');
        });
    }
}
