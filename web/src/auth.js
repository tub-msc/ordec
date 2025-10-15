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

function readCookies() {
    const cookies = {
        authKey: null,
        authHmacBypass: false,
    };
    document.cookie.split(';').forEach(el => {
        const split = el.split('=');
        const key = split[0].trim();
        const value = split.slice(1).join("=");
        if(key == 'ordecAuth') {
            cookies.authKey = value;
        } else if(key == 'ordecHmacBypass') {
            cookies.authHmacBypass = Boolean(value);
        }
    })
    return cookies;
}

export const cookies = readCookies();

export async function authenticateLocalQuery(queryLocal, queryHmac) {
    let valid;
    if(cookies.authHmacBypass) {
        // This workaround is **for the testing environment only**.
        // For some reason, the localhost in the testing environment might
        // be treated as insecure origin, causing window.crypto.subtle to be
        // unavailable.
        // In this testing environment, CSRF is not an issue.
        valid = true;
    } else {
        const hmacAuthKeyCrypto = await window.crypto.subtle.importKey(
            'raw',
            Uint8Array.fromHex(cookies.authKey),
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
