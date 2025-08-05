// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const urlParams = new URLSearchParams(window.location.search);
const authParam = urlParams.get('auth');
if(authParam) {
    urlParams.delete('auth');
    document.cookie = "ordecAuth="+window.escape(authParam)+';samesite=lax';
    // drop ?auth=... parameter from browser url
    window.history.pushState({}, document.title, window.location.pathname + '?' + urlParams.toString());
}
