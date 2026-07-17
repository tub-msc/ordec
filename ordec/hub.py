# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
JupyterHub single-user integration for the ORDeC web server.

When ordec is spawned by JupyterHub (e.g. via DockerSpawner, see hub/ in the
repository root), the hub routes ``/user/<name>/...`` to this server without
authenticating the requests itself. This module provides the pieces the
server needs to run behind the hub:

- **OAuth login against the hub**: browsers are redirected to the hub's
  OAuth authorize endpoint; the callback code is exchanged for a token,
  which identifies the hub user. Only the user this server was spawned for
  is accepted. Successful logins get a session cookie.
- **Auth-token handoff**: with a valid session cookie, the frontend fetches
  the ORDeC auth token from ``api/token`` (in classic standalone operation,
  the token travels in the URL fragment of the printed URL instead).
- **Activity reporting**: last-activity timestamps are POSTed to the hub so
  the idle culler (see hub/jupyterhub_config.py) can stop idle servers
  without misjudging long-lived websockets.

Everything here uses only the standard library; the ``jupyterhub`` package
is not required inside the user container. The HTTP-layer glue (routes,
responses, cookies on the wire) lives in server.py.
"""

import os
import json
import time
import secrets
import threading
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Bound the in-memory state/session stores. Both only grow through requests
# that already reached this server via the hub proxy, so these are
# anti-accident limits, not the primary defense.
MAX_PENDING_STATES = 100
STATE_TTL = 600  # seconds a pending OAuth state stays valid
MAX_SESSIONS = 100


def url_path_join(*parts):
    """Join URL path segments with single slashes, keeping a leading slash."""
    stripped = [p.strip('/') for p in parts]
    joined = '/'.join(p for p in stripped if p)
    return '/' + joined if joined else '/'


class HubAuthError(Exception):
    """OAuth code exchange or user lookup against the hub failed."""


class HubIntegration:
    COOKIE_SESSION = 'ordec-hub-session'
    COOKIE_STATE = 'ordec-hub-state'

    def __init__(self, *, prefix, api_url, api_token, client_id, user,
            callback_url=None, authorize_url=None, activity_url=None,
            server_name='', activity_interval=300):
        """
        Args:
            prefix: URL path prefix this server is proxied under
                (JUPYTERHUB_SERVICE_PREFIX, e.g. "/user/alice/").
            api_url: hub-internal REST API base (JUPYTERHUB_API_URL).
            api_token: this server's hub API token; doubles as the OAuth
                client secret (JUPYTERHUB_API_TOKEN).
            client_id: OAuth client id (JUPYTERHUB_CLIENT_ID).
            user: the hub user this server belongs to; the only user
                accepted by the login (JUPYTERHUB_USER).
            callback_url: browser-facing OAuth callback path
                (JUPYTERHUB_OAUTH_CALLBACK_URL); defaults to
                prefix + "oauth_callback".
            authorize_url: browser-facing hub OAuth authorize endpoint.
            activity_url: hub endpoint for activity reports
                (JUPYTERHUB_ACTIVITY_URL); None disables reporting.
            server_name: named-server name, '' for the default server.
            activity_interval: seconds between activity reports.
        """
        if not prefix.endswith('/'):
            prefix += '/'
        self.prefix = prefix
        self.api_url = api_url.rstrip('/')
        self.api_token = api_token
        self.client_id = client_id
        self.user = user
        self.callback_url = callback_url or (prefix + 'oauth_callback')
        self.authorize_url = authorize_url
        self.activity_url = activity_url
        self.server_name = server_name
        self.activity_interval = activity_interval

        self._lock = threading.Lock()
        self._states = {}    # state id -> (creation time, next_url)
        self._sessions = {}  # session id -> username
        self._last_activity = time.time()
        self._reported_activity = 0.0

    @classmethod
    def from_env(cls, environ=None):
        """
        Build a HubIntegration from the JUPYTERHUB_* environment variables
        the hub sets for spawned servers. Returns None when not spawned by
        a hub (or when ORDEC_HUB_DISABLE is set).
        """
        if environ is None:
            environ = os.environ
        prefix = environ.get('JUPYTERHUB_SERVICE_PREFIX')
        api_token = environ.get('JUPYTERHUB_API_TOKEN')
        if not prefix or not api_token or environ.get('ORDEC_HUB_DISABLE'):
            return None
        # Browser-facing authorize endpoint: hub host (often empty = same
        # host) + hub base URL + hub API path.
        authorize_url = environ.get('JUPYTERHUB_HOST', '') + url_path_join(
            environ.get('JUPYTERHUB_BASE_URL', '/'),
            'hub/api/oauth2/authorize')
        return cls(
            prefix=prefix,
            api_url=environ.get('JUPYTERHUB_API_URL',
                'http://127.0.0.1:8081/hub/api'),
            api_token=api_token,
            client_id=environ.get('JUPYTERHUB_CLIENT_ID', ''),
            user=environ.get('JUPYTERHUB_USER', ''),
            callback_url=environ.get('JUPYTERHUB_OAUTH_CALLBACK_URL'),
            authorize_url=authorize_url,
            activity_url=environ.get('JUPYTERHUB_ACTIVITY_URL'),
            server_name=environ.get('JUPYTERHUB_SERVER_NAME', ''),
        )

    # --- OAuth state (login CSRF protection) ---

    def new_state(self, next_url):
        """
        Register a pending OAuth login; returns the state id to put in both
        the authorize redirect and the state cookie. next_url is where the
        browser goes after a successful callback.
        """
        state = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            for k in [k for k, (t, _) in self._states.items()
                    if now - t > STATE_TTL]:
                del self._states[k]
            while len(self._states) >= MAX_PENDING_STATES:
                del self._states[next(iter(self._states))]
            self._states[state] = (now, next_url)
        return state

    def pop_state(self, state):
        """Consume a pending state; returns its next_url or None."""
        with self._lock:
            entry = self._states.pop(state, None)
        if entry is None:
            return None
        created, next_url = entry
        if time.time() - created > STATE_TTL:
            return None
        return next_url

    def authorize_redirect_url(self, state):
        return self.authorize_url + '?' + urlencode({
            'client_id': self.client_id,
            'redirect_uri': self.callback_url,
            'response_type': 'code',
            'state': state,
        })

    # --- OAuth code exchange ---

    def login_with_code(self, code):
        """
        Exchange the OAuth authorization code for a token and resolve the
        user it belongs to. Returns the username; raises HubAuthError when
        the hub rejects the code or the user is not this server's user.
        """
        body = urlencode({
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.callback_url,
            'client_id': self.client_id,
            'client_secret': self.api_token,
        }).encode('ascii')
        req = Request(self.api_url + '/oauth2/token', data=body)
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        try:
            with urlopen(req, timeout=10) as resp:
                access_token = json.loads(resp.read())['access_token']
        except (URLError, HTTPError, KeyError, ValueError) as e:
            raise HubAuthError(f"OAuth code exchange failed: {e}") from e

        req = Request(self.api_url + '/user')
        req.add_header('Authorization', f'token {access_token}')
        try:
            with urlopen(req, timeout=10) as resp:
                username = json.loads(resp.read())['name']
        except (URLError, HTTPError, KeyError, ValueError) as e:
            raise HubAuthError(f"hub user lookup failed: {e}") from e

        if username != self.user:
            raise HubAuthError(
                f"user {username!r} is not authorized for this server")
        return username

    # --- Sessions ---

    def new_session(self, username):
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            while len(self._sessions) >= MAX_SESSIONS:
                del self._sessions[next(iter(self._sessions))]
            self._sessions[session_id] = username
        return session_id

    def session_user_from_cookie(self, cookie_header):
        """Returns the authenticated username for a Cookie header, or None."""
        session_id = self.get_cookie(cookie_header, self.COOKIE_SESSION)
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    @staticmethod
    def get_cookie(cookie_header, name):
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return None
        morsel = cookie.get(name)
        return morsel.value if morsel else None

    def cookie_str(self, name, value, secure, max_age=None):
        """Set-Cookie value scoped to this server's prefix."""
        parts = [f"{name}={value}", f"Path={self.prefix}",
            "HttpOnly", "SameSite=Lax"]
        if secure:
            parts.append("Secure")
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        return "; ".join(parts)

    # --- Activity reporting ---

    def touch_activity(self):
        self._last_activity = time.time()

    def report_activity(self):
        """POST the last activity timestamp to the hub (if it advanced)."""
        if not self.activity_url:
            return
        last = self._last_activity
        if last <= self._reported_activity:
            return
        ts = datetime.fromtimestamp(last, timezone.utc).isoformat()
        payload = {
            'servers': {self.server_name: {'last_activity': ts}},
            'last_activity': ts,
        }
        req = Request(self.activity_url,
            data=json.dumps(payload).encode('utf8'))
        req.add_header('Authorization', f'token {self.api_token}')
        req.add_header('Content-Type', 'application/json')
        try:
            with urlopen(req, timeout=10):
                pass
        except (URLError, HTTPError) as e:
            # Non-fatal: the hub may be briefly unreachable; the next
            # interval retries. Worst case the idle culler acts on proxy
            # activity alone.
            print(f"hub activity report failed: {e}")
        else:
            self._reported_activity = last

    def start_activity_reporter(self):
        """Start the periodic activity reporter (daemon thread)."""
        if not self.activity_url:
            return
        def loop():
            # Initial report tells the hub the server is up and serving.
            self.report_activity()
            while True:
                time.sleep(self.activity_interval)
                self.report_activity()
        threading.Thread(target=loop, daemon=True,
            name='hub-activity-reporter').start()

    def service_url_bind(self, environ=None):
        """
        (hostname, port) to bind, from JUPYTERHUB_SERVICE_URL; None when the
        variable is absent.
        """
        if environ is None:
            environ = os.environ
        service_url = environ.get('JUPYTERHUB_SERVICE_URL')
        if not service_url:
            return None
        u = urlparse(service_url)
        return (u.hostname or '0.0.0.0', u.port or 8100)
