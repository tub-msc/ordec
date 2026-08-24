// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Entry point for index.html, the landing page (design gallery) shown at the
// site root. The in-app workspace has its own entry point in main.js
// (app.html). This page stays deliberately light: it does not pull in the app
// bundle (Golden Layout, Ace, WebGL), so it keeps its own small theme handling
// rather than importing theme.js.

import { initSession, session } from './auth.js';

// The saved theme is applied before render by a small inline script in
// index.html (avoids a light flash); here we only wire the toggle button,
// reading the initial state back off the body class it set.
const btn = document.querySelector('#theme-toggle');
function updateToggleBtn(isDark) {
    btn.textContent = isDark ? '\u2600' : '\u263E';
    btn.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
}
updateToggleBtn(document.body.classList.contains('theme-dark'));
btn.addEventListener('click', () => {
    const nowDark = !document.body.classList.contains('theme-dark');
    document.body.classList.toggle('theme-dark', nowDark);
    window.localStorage.setItem('ordecTheme', nowDark ? 'dark' : 'light');
    updateToggleBtn(nowDark);
});

// Version info; documentation links get their href set to the version-matched
// URL (see the data-docs-page comment in index.html). Relative path: Vite only
// rewrites asset references for base './', not fetch() literals, and
// '/api/version' would 404 behind the /user/<name>/ prefix of JupyterHub.
fetch('api/version')
    .then(r => r.json())
    .then(data => {
        document.querySelector('#version').textContent = data['version'];
        document.querySelectorAll('a[data-docs-page]').forEach(a => {
            a.href = data['docs_url'] + a.dataset.docsPage;
        });
    })
    .catch(err => console.error('Failed to fetch api/version:', err));

// Strip #auth= from the URL and save the token for app.html to read.
// initSession() also probes api/token, which behind JupyterHub carries hubMode
// and the logout URL; wire the "End session" control from that (the same wiring
// lives in main.js for the app page — keep in sync).
await initSession();
// The competition course needs the hub's scoreboard service, which is
// enabled per workshop (ORDEC_HUB_SCOREBOARD); without it the course stays
// unlisted (but reachable by URL).
if (session.scoreboardUrl) {
    document.querySelector('#competitionSection').hidden = false;
}
if (session.hubMode && session.hubLogoutUrl) {
    const endSession = document.querySelector('#hubEndSession');
    endSession.href = session.hubLogoutUrl;
    endSession.hidden = false;
    endSession.addEventListener('click', (e) => {
        if (!window.confirm('End this session? Your container will be '
                + 'stopped and unsaved work will be lost.')) {
            e.preventDefault();
        }
    });
}
