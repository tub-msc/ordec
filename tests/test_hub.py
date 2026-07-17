# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the JupyterHub integration (ordec/hub.py + the hub gate in
server.py): base-path serving, the OAuth login flow against a fake hub,
api/token handoff, websocket cookie gating and activity reporting.
No browser and no real JupyterHub required.
"""

import json
import queue
import socket
import threading
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import pytest
from websockets.sync.client import connect
from websockets.exceptions import InvalidStatus

from ordec import server
from ordec.hub import HubIntegration, HubAuthError

PREFIX = '/user/alice/'
API_TOKEN = 'apitoken-secret'
CLIENT_ID = 'jupyterhub-user-alice'

# code -> (access token, username) issued by the fake hub
HUB_CODES = {
    'goodcode': ('at-alice', 'alice'),
    'evilcode': ('at-bob', 'bob'),
}


class FakeHubHandler(BaseHTTPRequestHandler):
    """Just enough of the JupyterHub REST API for the OAuth flow."""

    def _json(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode()
        if self.path == '/hub/api/oauth2/token':
            form = parse_qs(body)
            if form.get('client_secret') != [API_TOKEN]:
                return self._json(403, {'error': 'bad client secret'})
            code = form.get('code', [None])[0]
            if code not in HUB_CODES:
                return self._json(403, {'error': 'bad code'})
            return self._json(200, {'access_token': HUB_CODES[code][0]})
        if self.path == '/hub/api/users/alice/activity':
            if self.headers.get('Authorization') != f'token {API_TOKEN}':
                return self._json(403, {'error': 'bad token'})
            self.server.activity_posts.append(json.loads(body))
            return self._json(200, {})
        self._json(404, {'error': 'not found'})

    def do_GET(self):
        if self.path == '/hub/api/user':
            auth = self.headers.get('Authorization', '')
            for access_token, username in HUB_CODES.values():
                if auth == f'token {access_token}':
                    return self._json(200, {'name': username, 'kind': 'user'})
            return self._json(403, {'error': 'bad token'})
        self._json(404, {'error': 'not found'})

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def fake_hub():
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), FakeHubHandler)
    httpd.activity_posts = []
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()


def make_hub(fake_hub):
    hub_port = fake_hub.server_address[1]
    return HubIntegration(
        prefix=PREFIX,
        api_url=f'http://127.0.0.1:{hub_port}/hub/api',
        api_token=API_TOKEN,
        client_id=CLIENT_ID,
        user='alice',
        authorize_url='http://hub.example/hub/api/oauth2/authorize',
        logout_url='http://hub.example/hub/logout',
        activity_url=f'http://127.0.0.1:{hub_port}/hub/api/users/alice/activity',
    )


@pytest.fixture(scope="module")
def hub_server(fake_hub):
    """ordec server behind a (fake) hub, serving under PREFIX."""
    port = free_port()
    key = server.ServerKey()
    hub = make_hub(fake_hub)
    static_handler = server.StaticHandler(base_path=PREFIX, hub=hub, key=key)
    startup_queue = queue.Queue(maxsize=1)
    t = threading.Thread(target=server.server_thread,
        args=('127.0.0.1', port, static_handler, key, startup_queue),
        kwargs={'on_activity': hub.touch_activity}, daemon=True)
    t.start()
    startup_error = startup_queue.get()
    if startup_error is not None:
        raise RuntimeError(f"Test server failed to start: {startup_error}")
    return port, key, hub


def request(port, path, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        conn.request('GET', path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, dict_headers(resp), resp.read()
    finally:
        conn.close()


def dict_headers(resp):
    headers = {}
    for k, v in resp.getheaders():
        headers.setdefault(k, []).append(v)
    return headers


def get_cookie_value(headers, name):
    for set_cookie in headers.get('Set-Cookie', []):
        if set_cookie.startswith(name + '='):
            return set_cookie.split(';')[0].split('=', 1)[1]
    return None


def login(port, entry_path=PREFIX):
    """Walk the OAuth flow like a browser; returns the session cookie."""
    # 1. Unauthenticated page navigation -> redirect to hub authorize:
    status, headers, _ = request(port, entry_path,
        {'Accept': 'text/html'})
    assert status == 302
    location = headers['Location'][0]
    assert location.startswith('http://hub.example/hub/api/oauth2/authorize?')
    query = parse_qs(urlparse(location).query)
    assert query['client_id'] == [CLIENT_ID]
    assert query['redirect_uri'] == [PREFIX + 'oauth_callback']
    state = query['state'][0]
    state_cookie = get_cookie_value(headers, 'ordec-hub-state')
    assert state_cookie == state

    # 2. The hub redirects back to the callback with a code (simulated):
    status, headers, _ = request(port,
        f'{PREFIX}oauth_callback?code=goodcode&state={state}',
        {'Cookie': f'ordec-hub-state={state}'})
    assert status == 302
    assert headers['Location'][0] == entry_path
    session_cookie = get_cookie_value(headers, 'ordec-hub-session')
    assert session_cookie
    return f'ordec-hub-session={session_cookie}'


def test_oauth_flow_and_token_handoff(hub_server):
    port, key, hub = hub_server
    cookie = login(port)

    # api/token hands the auth token to the authenticated browser:
    status, headers, body = request(port, f'{PREFIX}api/token',
        {'Cookie': cookie})
    assert status == 200
    assert json.loads(body) == {
        'auth': key.token(),
        'hub_logout_url': hub.logout_url,
    }

    # ...but not without the session cookie:
    status, _, _ = request(port, f'{PREFIX}api/token')
    assert status == 401

    # Other API routes work once authenticated:
    status, _, body = request(port, f'{PREFIX}api/version',
        {'Cookie': cookie})
    assert status == 200
    assert 'version' in json.loads(body)


def test_oauth_rejects_wrong_user(hub_server):
    port, _, _ = hub_server
    status, headers, _ = request(port, PREFIX, {'Accept': 'text/html'})
    state = get_cookie_value(headers, 'ordec-hub-state')

    # A code belonging to another hub user must not create a session:
    status, headers, _ = request(port,
        f'{PREFIX}oauth_callback?code=evilcode&state={state}',
        {'Cookie': f'ordec-hub-state={state}'})
    assert status == 403
    assert get_cookie_value(headers, 'ordec-hub-session') is None


def test_oauth_rejects_state_mismatch(hub_server):
    port, _, _ = hub_server
    status, headers, _ = request(port, PREFIX, {'Accept': 'text/html'})
    state = get_cookie_value(headers, 'ordec-hub-state')

    # Callback without the matching state cookie (login CSRF):
    status, _, _ = request(port,
        f'{PREFIX}oauth_callback?code=goodcode&state={state}')
    assert status == 403
    # Callback with a fabricated state:
    status, _, _ = request(port,
        f'{PREFIX}oauth_callback?code=goodcode&state=forged',
        {'Cookie': 'ordec-hub-state=forged'})
    assert status == 403


def test_base_path_enforcement(hub_server):
    port, _, _ = hub_server
    # Outside the prefix: 404, no OAuth redirect.
    status, _, _ = request(port, '/api/version', {'Accept': 'text/html'})
    assert status == 404
    # Prefix without trailing slash redirects to the prefix:
    status, headers, _ = request(port, PREFIX.rstrip('/'))
    assert status == 302
    assert headers['Location'][0] == PREFIX


def test_unauthenticated_api_gets_401(hub_server):
    port, _, _ = hub_server
    # Non-navigation requests get 401 instead of an OAuth redirect:
    status, _, _ = request(port, f'{PREFIX}api/version')
    assert status == 401


def test_websocket_cookie_gating(hub_server):
    port, key, _ = hub_server
    url = f'ws://127.0.0.1:{port}{PREFIX}api/websocket'

    # Without the session cookie, the handshake must be rejected:
    with pytest.raises(InvalidStatus) as excinfo:
        connect(url)
    assert excinfo.value.response.status_code == 401

    # With cookie: full protocol works (token from api/token):
    cookie = login(port)
    _, _, body = request(port, f'{PREFIX}api/token', {'Cookie': cookie})
    auth = json.loads(body)['auth']
    with connect(url, additional_headers={'Cookie': cookie}) as sock:
        sock.send(json.dumps({'msg': 'source', 'srctype': 'python',
            'src': 'x = 42', 'auth': auth}))
        msg = json.loads(sock.recv(timeout=30))
        assert msg['msg'] == 'viewlist'


def test_activity_reporting(hub_server, fake_hub):
    port, _, hub = hub_server
    posts_before = len(fake_hub.activity_posts)
    hub.touch_activity()
    hub.report_activity()
    assert len(fake_hub.activity_posts) == posts_before + 1
    post = fake_hub.activity_posts[-1]
    assert 'last_activity' in post
    assert post['servers']['']['last_activity'] == post['last_activity']

    # Unchanged activity is not re-reported:
    hub.report_activity()
    assert len(fake_hub.activity_posts) == posts_before + 1


def test_login_with_code_direct(fake_hub):
    hub = make_hub(fake_hub)
    assert hub.login_with_code('goodcode') == 'alice'
    with pytest.raises(HubAuthError):
        hub.login_with_code('evilcode')  # wrong user
    with pytest.raises(HubAuthError):
        hub.login_with_code('nonsense')  # unknown code


def test_from_env():
    env = {
        'JUPYTERHUB_SERVICE_PREFIX': '/user/alice/',
        'JUPYTERHUB_API_TOKEN': 't',
        'JUPYTERHUB_API_URL': 'http://hub:8081/hub/api',
        'JUPYTERHUB_CLIENT_ID': 'cid',
        'JUPYTERHUB_USER': 'alice',
        'JUPYTERHUB_BASE_URL': '/',
        'JUPYTERHUB_SERVICE_URL': 'http://0.0.0.0:8100',
    }
    hub = HubIntegration.from_env(env)
    assert hub is not None
    assert hub.prefix == '/user/alice/'
    assert hub.authorize_url == '/hub/api/oauth2/authorize'
    assert hub.logout_url == '/hub/logout'
    assert hub.callback_url == '/user/alice/oauth_callback'
    assert hub.service_url_bind(env) == ('0.0.0.0', 8100)

    assert HubIntegration.from_env({}) is None
    assert HubIntegration.from_env(dict(env, ORDEC_HUB_DISABLE='1')) is None


@pytest.fixture(scope="module")
def prefix_server():
    """Server with --base-url style prefix but no hub."""
    port = free_port()
    key = server.ServerKey()
    static_handler = server.StaticHandler(base_path='/pfx/', key=key)
    startup_queue = queue.Queue(maxsize=1)
    t = threading.Thread(target=server.server_thread,
        args=('127.0.0.1', port, static_handler, key, startup_queue),
        daemon=True)
    t.start()
    startup_error = startup_queue.get()
    if startup_error is not None:
        raise RuntimeError(f"Test server failed to start: {startup_error}")
    return port, key


def test_base_path_without_hub(prefix_server):
    port, key = prefix_server
    status, _, body = request(port, '/pfx/api/version')
    assert status == 200
    assert 'version' in json.loads(body)
    # Outside the prefix:
    status, _, _ = request(port, '/api/version')
    assert status == 404
    # No hub: api/token does not exist (falls through to static 404):
    status, _, _ = request(port, '/pfx/api/token')
    assert status == 404
    # Websocket needs no cookie without a hub:
    with connect(f'ws://127.0.0.1:{port}/pfx/api/websocket') as sock:
        sock.send(json.dumps({'msg': 'source', 'srctype': 'python',
            'src': 'x = 1', 'auth': key.token()}))
        msg = json.loads(sock.recv(timeout=30))
        assert msg['msg'] == 'viewlist'
