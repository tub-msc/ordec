# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
WebSocket server for use in conjunction with the new web interface.
"""

import argparse
from websockets.sync.server import serve
from websockets.http11 import Request, Response
from websockets.datastructures import Headers
import http
import json
import traceback
from pathlib import Path
import mimetypes
from urllib.parse import urlparse, parse_qs
import threading
import signal
import importlib.resources
import tarfile
from functools import partial
import secrets
import io
import time
import tempfile

from .core import *
from .ord1.parser import ord2py
from .lib import examples

def build_cells(source_type: str, source_data: str) -> (dict, dict):
    conn_globals = {}
    if source_type == 'python' or source_type == 'ord':
        try:
            if source_type == 'ord':
                code = compile(ord2py(source_data), "<string>", "exec")
                exec(code, conn_globals, conn_globals)
            else:
                exec(source_data, conn_globals, conn_globals)
        except Exception:
            #print("Reporting exception.")
            return {
                'msg':'exception',
                'exception':traceback.format_exc(),
            }, None
        else:
            views = []
            for k, v in conn_globals.items():
                if not (isinstance(v, type) and issubclass(v, Cell) and v!=Cell):
                    continue
                cell_views = [elem for elem in dir(v()) if (not elem.startswith('__')) and (not elem in ('children', 'instances', 'params', 'params_list', 'netlist_ngspice', 'cached_subgraphs', 'spiceSymbol'))]
                for v in cell_views:
                    views.append(f'{k}().{v}')
            #print(f"Reporting {len(views)} views.")
            return {
                'msg':'views',
                'views':views,
            }, conn_globals
    else:
        raise NotImplementedError(f'source_type {source_type} not implemented')

def query_view(view_name, conn_globals):
    msg_ret = {
        'msg':'view',
        'view':view_name,
    }

    try:
        view = eval(view_name, conn_globals, conn_globals)
        viewtype, data = view.webdata()
        msg_ret['type'] = viewtype
        msg_ret['data'] = data
    except Exception:    
        msg_ret['exception'] = traceback.format_exc()

    return msg_ret

def handle_connection(websocket, auth_token):
    remote = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    print(f"{remote}: new websocket connection")
    msgs = iter(websocket)

    # Validate auth_token to prevent code execution from untrusted connections:
    msg_first = json.loads(next(msgs))
    if auth_token:
        if not secrets.compare_digest(auth_token, msg_first['auth']):
            websocket.send(json.dumps({
                'msg':'exception',
                'exception':"incorrect auth token provided",
                }))
            return

    # First message - read design input / build cells:
    assert msg_first['msg'] == 'source'
    source_type = msg_first['srctype']
    source_data = msg_first['src']
    #print(f"Received source of type {source_type}.")
    msg_ret, conn_globals = build_cells(source_type, source_data)
    websocket.send(json.dumps(msg_ret))
    if not conn_globals:
        return

    for msg_raw in websocket:
        msg = json.loads(msg_raw)
        assert msg['msg'] == 'getview'
        view_name = msg['view']
        #print(f"View {view_name} was requested.")

        msg_ret = query_view(view_name, conn_globals)
        websocket.send(json.dumps(msg_ret))
    print(f"{remote}: websocket connection ended")

def build_response(status: http.HTTPStatus=http.HTTPStatus.OK, mime_type: str='text/plain', data: bytes=None):
    if data == None:
        data = status.name.encode("ascii")
    return Response(
        int(status),
        status.name,
        Headers(**{"Content-Type": mime_type, "Content-Length": str(len(data)), }),
        data,
    )

def anonymous_tar(p: Path) -> tarfile.TarFile:
    f = io.BytesIO()
    def strip_path(tarinfo):
        fn = str((Path('/')/(tarinfo.name)).relative_to(Path('/')/p))
        if not fn.startswith('.'):
            fn = './' + fn
        tarinfo.name = fn
        return tarinfo
    with tarfile.open(fileobj=f, mode='w') as t:
        t.add(p, filter=strip_path)
    f.seek(0)
    return tarfile.open(fileobj=f, mode='r')

def tar_path(p: Path) -> str:
    if len(p.parts) == 0:
        return '.'
    else:
        return f'./{p}'

class StaticHandler:
    """
    This adds a static file HTTP server to the websockets HTTP server.
    This way, for local demos it is not needed to run two separate servers.
    For development or (possible future) multi-user production setups,
    this should not be used.

    This class obtains static files from a tar file rather than a classical
    directory tree. The advantage of this is that we do not pollute the Python
    package tree with a hierarchy of packages/directories that really only
    matter for this HTTP server.
    """

    def __init__(self, tar: tarfile.TarFile=None):
        self.tar = tar
        self.tar_semaphore = threading.Semaphore()

        
    def process_request(self, connection, request):
        try:
            url=urlparse(request.path)
            if url.path.startswith('/'):
                req_path = Path(url.path[1:])
            else:
                req_path = Path(url.path)

            if req_path == Path('api/websocket'):
                return None # --> for websocket connection

            if req_path == Path('api/example'):
                query = parse_qs(url.query)
                return self.process_request_example(query['name'][0])

            return self.process_request_static(req_path)
        except:
            print(traceback.print_exc())
            return build_response(http.HTTPStatus.INTERNAL_SERVER_ERROR)

    def process_request_example(self, name):
        src = ''
        srctype = 'Python'
        uistate = {}
        for p in importlib.resources.files(examples).iterdir():
            if p.stem == name:
                src = p.read_text()
                srctype = {'.ord': 'ord', '.py': 'python'}[p.suffix]
            if p.name == f'{name}.uistate.json':
                with open(p) as f:
                    uistate = json.load(f)
        data = json.dumps({
            'src':src,
            'srctype': srctype,
            'uistate':uistate,
        })
        return build_response(data=data.encode('utf8'), mime_type='application/json')

    def process_request_static(self, req_path):
        if not self.tar:
            return build_response(http.HTTPStatus.NOT_FOUND)
        
        # tarfile.TarFile seems not to be thread-safe, a semaphore seems to fix this.
        with self.tar_semaphore:
            try:
                info = self.tar.getmember(tar_path(req_path))
                if info.type == tarfile.DIRTYPE:
                    req_path = req_path / 'index.html'
                    info = self.tar.getmember(tar_path(req_path))
            except KeyError:
                return build_response(http.HTTPStatus.NOT_FOUND)

            data = self.tar.extractfile(info).read()

        try:
            mime_type = mimetypes.types_map[req_path.suffix]
        except KeyError:
            mime_type = 'application/octet-stream'

        return build_response(http.HTTPStatus.OK, mime_type=mime_type, data=data)    

def secure_url_open(user_url):
    """
    user_url includes the secret auth_token, which potentially allows
    arbitrary code generation / privilege escalation. When we open this user_url
    in a browser, we must ensure that the secret is not leaked through the
    command line arguments (argv) of the browser. This is done by this
    function, which uses an private temporary file as redirect. The path of
    this file is not secret, but the file (which should only be readable by
    the user) contains the secret auth_token.
    
    This is similar to Jupyter Notebook's auth token setup.
    """

    launch_html = tempfile.NamedTemporaryFile('w', suffix='.html', delete=True)
    launch_html.write(
        '<!DOCTYPE html>\n'
        '<html>\n'
        f'<head><meta charset="UTF-8"><meta http-equiv="refresh" content="1;url={user_url}" /></head>\n'
        f'<body><a href="{user_url}">Go to ORDeC!</a><script>window.location.href = "{user_url}";</script></body>\n'
        '</html>\n'
        )
    launch_html.flush()

    import webbrowser
    webbrowser.open(launch_html.name)

    return launch_html

cli_help = """
ORDeC, a custom IC design platform.

There are three recommended variants to run ordec-server:

(1) Combined frontend + backend server with regular installation:
    A regular installation of ORDeC includes a compiled version of the
    frontend (webdist.tar). In this case, ORDeC can be started through
    a simple 'ordec-server -b'.

(2) Combined frontend + backend server with editable installation:
    In case of a editable installation ("develop mode" / pip -e), variant (1)
    is not supported, as webdist.tar is not available in the package.
    Instead, the frontend can be build separately through 'npm run build' in
    the web/ directory. The build results must then be supplied to the
    ordec-server command: 'ordec-server -b -r [...]/web/dist/'

(3) Separate frontend + backend server for frontend development:
    In the web/ directory, run the Vite frontend server using 'npm run dev'.
    Then, separately start the backend server using 'ordec-server -n -b'.
    This gives the best development experience when working on the frontend
    code. In this variant, the Vite server acts as proxy for the backend
    server. Thus, you should use the browser only to connect to the Vite
    server / port.
"""

def main():
    parser = argparse.ArgumentParser(prog='ordec-server',
        description=cli_help,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('-l', '--hostname', default="127.0.0.1", help="Hostname to listen on (default 127.0.0.1).")
    parser.add_argument('-p', '--port', default=8100, type=int, help="Port to listen on (default 8100).")
    parser.add_argument('-r', '--static-root', help="Path for static web resources. If not specified, the webdist.tar file included in the ORDeC installation is used.", nargs='?')
    parser.add_argument('-n', '--no-frontend', action='store_true', help="Serve backend only. Requires a separate server (e.g. Vite) to serve the frontend.")
    parser.add_argument('-b', '--launch-browser', action='store_true', help="Automatically open ORDeC in browser.")
    
    args = parser.parse_args()
    hostname = args.hostname
    port = args.port

    auth_token = secrets.token_urlsafe()

    launch_html = None

    user_url = f"http://{hostname}:{port}/?auth={auth_token}"

    if args.no_frontend:
        static_handler = StaticHandler()
        # Vite provides the frontend for the user on port 5173:
        print("--no-frontend: Make sure to run 'npm run dev' in web/ in addition to 'ordec-server'.")
        user_url = f"http://localhost:5173/?auth={auth_token}"
    elif args.static_root:
        static_handler = StaticHandler(anonymous_tar(args.static_root))
    else:
        webdist_tar = importlib.resources.files(__package__) / 'webdist.tar'
        try:
            static_handler = StaticHandler(tarfile.open(webdist_tar))
        except FileNotFoundError:
            print(
                "ERROR: webdist.tar not found. -- This is likely an editable "
                "installation. Please use variant (2) or (3) outlined below to "
                "run the server.\n"
                )
            parser.print_help()
            raise SystemExit(1)

    # Launch server in separate daemon thread (daemon=True). The connection
    # threads automatically inherit the daemon property. All daemon threads
    # are terminated when the main thread terminates. This makes it possible
    # to terminate the whole thing with a single Ctrl+C.
    # A future version of the websockets library might make this workaround
    # unnecessary.
    threading.Thread(target=server_thread, args=(hostname, port, static_handler, auth_token), daemon=True).start()

    print(f"To start ORDeC, navigate to: {user_url}")
    time.sleep(1)

    if args.launch_browser:
        launch_html = secure_url_open(user_url)

    try:
        while True:
            signal.pause()
    except KeyboardInterrupt:
        print("Terminating.")
    finally:
        if launch_html:
            launch_html.close() # Deletes the temporary file.

def server_thread(hostname, port, static_handler, auth_token):
    h = partial(handle_connection, auth_token=auth_token)
    with serve(h, hostname, port, process_request=static_handler.process_request) as server:
        #print(f"Listening on {hostname}, port {port}")
        server.serve_forever()
