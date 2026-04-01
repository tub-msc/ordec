// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Import both Golden Layout themes. Only one will be active at a time;
// the inactive one is disabled via its stylesheet's .disabled property.
import glLightUrl from "golden-layout/dist/css/themes/goldenlayout-light-theme.css?url";
import glDarkUrl from "golden-layout/dist/css/themes/goldenlayout-dark-theme.css?url";

const STORAGE_KEY = 'ordecTheme';

let glLightLink = null;
let glDarkLink = null;
let aceEditors = [];

function createGlLinks() {
    glLightLink = document.createElement('link');
    glLightLink.rel = 'stylesheet';
    glLightLink.href = glLightUrl;
    document.head.appendChild(glLightLink);

    glDarkLink = document.createElement('link');
    glDarkLink.rel = 'stylesheet';
    glDarkLink.href = glDarkUrl;
    document.head.appendChild(glDarkLink);
}

function isDark() {
    return document.body.classList.contains('theme-dark');
}

function applyTheme(dark) {
    if (dark) {
        document.body.classList.add('theme-dark');
    } else {
        document.body.classList.remove('theme-dark');
    }

    if (glLightLink && glDarkLink) {
        glLightLink.disabled = dark;
        glDarkLink.disabled = !dark;
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

export function initTheme() {
    createGlLinks();

    const saved = window.localStorage.getItem(STORAGE_KEY);
    const dark = saved === 'dark';
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
