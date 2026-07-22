// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const urlParams = new URLSearchParams(window.location.hash.substring(1));
const authParam = urlParams.get('auth');
if(authParam) {
    urlParams.delete('auth');
    window.localStorage.setItem('ordecAuth', authParam);
    // drop auth parameter from browser url fragment
    const remaining = urlParams.toString();
    window.history.pushState({}, document.title, window.location.pathname + (remaining ? '#' + remaining : ''));
}

export const session = {
    authKey: window.localStorage.getItem('ordecAuth'),
    authHmacBypass: window.localStorage.getItem('ordecHmacBypass'),
    hubMode: false,
    hubLogoutUrl: null,
};

export async function initSession() {
    // JupyterHub-hosted deployments (see ordec/hub.py) deliver the backend
    // auth token via the cookie-gated api/token endpoint instead of the URL
    // fragment. The endpoint's token is authoritative: it always belongs to
    // the currently running server process, whereas localStorage may hold a
    // stale token from before an idle-culled instance was respawned.
    // Standalone servers have no api/token route (404) and keep the
    // fragment/localStorage flow.
    try {
        const response = await fetch('api/token');
        if (response.ok) {
            const data = await response.json();
            session.authKey = data.auth;
            session.hubMode = true;
            session.hubLogoutUrl = data.hub_logout_url;
        }
    } catch (e) {
        // Network error: not hub-hosted or server gone; fall back to the
        // fragment/localStorage token.
    }
}

export async function authenticateLocalQuery(queryLocal, queryHmac) {
    let valid;
    if(session.authHmacBypass) {
        // SECURITY WARNING: This workaround is **for the testing environment only**.
        // For some reason, the localhost in the testing environment might
        // be treated as insecure origin, causing window.crypto.subtle to be
        // unavailable.
        // In this testing environment, CSRF is not an issue.
        //
        // This bypass should NEVER be enabled in production use.
        // It can only be activated by setting localStorage.ordecHmacBypass,
        // which requires same-origin access (not possible from external sites).
        console.warn("SECURITY WARNING: HMAC bypass is enabled. This should only be used in testing environments.");
        valid = true;
    } else {
        const hmacAuthKeyCrypto = await window.crypto.subtle.importKey(
            'raw',
            Uint8Array.fromHex(session.authKey),
            {name: 'HMAC', hash: {name: 'SHA-256'}},
            false,
            ['verify']
        );

        const encoder = new TextEncoder();
        valid = await window.crypto.subtle.verify(
            'HMAC',
            hmacAuthKeyCrypto,
            Uint8Array.fromHex(queryHmac),
            encoder.encode(queryLocal)
        );
    }

    if(valid) {
        const s = queryLocal.split(":", 2);
        return {
            module: s[0],
            view: s[1],
        };
    } else {
        return null;
    }
}
