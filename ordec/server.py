# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
``ordec-server`` is the command line tool to start the web interface of
ORDeC, the custom IC design platform.

There are three recommended setups to run ``ordec-server``:

(1) **Combined frontend + backend server with regular installation:**
    A regular installation of ORDeC includes a compiled version of the
    frontend (webdist.tar). In this case, ORDeC can be started through
    a simple ``ordec-server``.

(2) **Combined frontend + backend server with editable installation:**
    In case of a editable installation ("develop mode" / pip -e), setup (1)
    is not supported, as webdist.tar is not available in the package.
    Instead, the frontend can be build separately through 'npm run build' in
    the web/ directory. The build results must then be supplied to the
    ordec-server command: ``ordec-server -r [...]/web/dist/``

(3) **Separate frontend + backend server for frontend development:**
    In the web/ directory, run the Vite frontend server using 'npm run dev'.
    Then, separately start the backend server using ``ordec-server -b``.
    This gives the best development experience when working on the frontend
    code. In this setup, the Vite server acts as proxy for the backend
    server. Thus, you should use the browser only to connect to the Vite
    server / port.

Furthermore, there are two modes in which you can use the ORDeC web UI:

(1) **Integrated mode:**
    The source code is entered through the web UI's integrated editor. The
    design is rebuilt automatically when the source is changed. The entered
    source code is not saved anywhere. Please save any code that you want to
    keep manually using copy & paste to local files.

    Unless ``--module`` (``-m``) is specified, the web UI is launched in
    integrated mode.

(2) **Local mode:**
    Source code is entered and stored in the local file system. An editor
    outside the web browser is used. The design is rebuilt automatically when
    it is detected that source files have changed. This is done using inotify.

    By specifying ``--module`` (``-m``) and optionally ``--view`` (``-w``),
    the web interface is launched in local mode.

    The specified module name (e.g. ``--module mydesign``) is treated as regular
    Python module import. It could reference a single Python file mydesign.py,
    a single ORD file mydesign.ord, or a directory mydesign/ containing an
    __init__.py (which enables projects / packages with multiple modules / 
    source files). Hierarchical names such as mydesign.submodule are permitted
    as well.
"""

import argparse
import http
import json
import traceback
from pathlib import Path
from types import ModuleType
import mimetypes
from urllib.parse import urlparse, parse_qs
import threading
import signal
import importlib
import importlib.resources
import tarfile
import secrets
import io
import time
import tempfile
import sys
import os
import select

import inotify_simple
from websockets.sync.server import serve
from websockets.http11 import Request, Response
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedOK

from . import importer
from .version import version
from .core import *

def discover_views(conn_globals, recursive=True, modules_visited=None):
    if modules_visited == None:
        modules_visited = set()
    views = []
    for k, v in conn_globals.items():
        if isinstance(v, ModuleType) and recursive:
            if v in modules_visited:
                continue
            modules_visited.add(v)
            for subview in discover_views(v.__dict__, recursive=recursive, modules_visited=modules_visited):
                subview['name'] = f"{k}.{subview['name']}"
                views.append(subview)
        elif isinstance(v, generate_func):
            views.append({'name': f"{k}()"} | v.info_dict())
        elif isinstance(v, type) and issubclass(v, Cell) and v!=Cell:
            generate_members = []
            for member_name in dir(v):
                member = getattr(v, member_name)
                if isinstance(member, generate):
                    generate_members.append((member_name, member))
                    
            for instance in v.discoverable_instances():
                for member_name, member in generate_members:
                    name = f'{instance!r}.{member_name}'
                    views.append({'name': name} | member.info_dict())
            
    return views

class ConnectionHandler:
    def __init__(self, auth_token, sysmodules_orig):
        self.sysmodules_orig = set(sysmodules_orig.keys())
        self.auth_token = auth_token
        self.import_lock = threading.Lock()
        # import_lock is not perfect. Ideally, we would have a RW lock which
        # ensure that no other thread is evaluating view requests when import_lock
        # is acquired.

    def query_view(self, view_name, conn_globals):
        msg_ret = {
            'msg':'view',
            'view':view_name,
        }

        try:
            with self.import_lock:
                view = eval(view_name, conn_globals, conn_globals)
                viewtype, data = view.webdata()
            msg_ret['type'] = viewtype
            msg_ret['data'] = data
        except:    
            msg_ret['exception'] = traceback.format_exc()

        return msg_ret

    def build_cells(self, source_type: str, source_data: str) -> (dict, dict):
        conn_globals = {}
        try:
            if source_type == 'ord':
                # Having the import here enables auto-realoading of ord1.
                from .ord1.parser import ord2py
                code = compile(ord2py(source_data), "<string>", "exec")
                exec(code, conn_globals, conn_globals)
            elif source_type == 'python':
                exec(source_data, conn_globals, conn_globals)
            else:
                raise NotImplementedError(f'source_type {source_type} not implemented')
        except:
            #print("Reporting exception.")
            return {
                'msg':'exception',
                'exception':traceback.format_exc(),
            }, None
        else:
            return {
                'msg':'viewlist',
                'views':discover_views(conn_globals),
            }, conn_globals

    def purge_modules(self):
        """
        Removes all modules from sys.modules that were not in sys.modules
        before the first build_cells or build_localmodule call. This ensures that
        re-imports read the sources freshly.

        Only call this method with self.import_lock acquired.
        """
        for k in list(sys.modules.keys()):
            if k not in self.sysmodules_orig:
                #print(f"Unloading {k}...")
                del sys.modules[k]

    def watch_files(self):
        ret = []
        for k, v in sys.modules.items():
            if k not in self.sysmodules_orig:
                try:
                    ret.append(v.__file__)
                except AttributeError:
                    pass
        return ret

    def build_localmodule(self, localmodule: str):
        with self.import_lock:
            self.purge_modules()
            try:
                #print(f"Importing {localmodule}...")
                module = importlib.import_module(localmodule)
                conn_globals = module.__dict__
            except:
                return {
                    'msg':'exception',
                    'exception':traceback.format_exc(),
                }, None, self.watch_files()
            else:
                return {
                    'msg':'viewlist',
                    'views':discover_views(conn_globals),
                }, conn_globals, self.watch_files()

    def handle_connection(self, websocket):
        remote = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        print(f"{remote}: new websocket connection")
        msgs = iter(websocket)

        # Validate auth_token to prevent code execution from untrusted connections:
        msg_first = json.loads(next(msgs))
        if not secrets.compare_digest(self.auth_token, msg_first['auth']):
            websocket.send(json.dumps({
                'msg':'exception',
                'exception':"incorrect auth token provided",
                }))
            return

        # First message - read design input / build cells:
        if msg_first['msg'] == 'source':
            #print(f"Received source of type {source_type}.")
            msg_ret, conn_globals = self.build_cells(msg_first['srctype'], msg_first['src'])
            watch_files = []
        elif msg_first['msg'] == 'localmodule':
            msg_ret, conn_globals, watch_files = self.build_localmodule(msg_first['module'])
        else:
            raise Exception("Excpected 'source' or 'localmodule' message.")
        websocket.send(json.dumps(msg_ret))
        if not conn_globals:
            return

        if watch_files:
            pipe_inotify_abort_r_fd, pipe_inotify_abort_w_fd = os.pipe()
            pipe_inotify_abort_r = os.fdopen(pipe_inotify_abort_r_fd, 'r')
            pipe_inotify_abort_w = os.fdopen(pipe_inotify_abort_w_fd, 'w')
            watch_thread = threading.Thread(target=background_inotify,
                args=(watch_files, pipe_inotify_abort_r, websocket), daemon=True)
            watch_thread.start()
        try:
            for msg_raw in websocket:
                msg = json.loads(msg_raw)
                assert msg['msg'] == 'getview'
                view_name = msg['view']
                #print(f"View {view_name} was requested.")

                msg_ret = self.query_view(view_name, conn_globals)
                websocket.send(json.dumps(msg_ret))
        finally:
            if watch_files:
                pipe_inotify_abort_w.write("abort!")
                pipe_inotify_abort_w.flush()
                # "abort!" is just a dummy message to trigger select() and 
                # stop the inotify thread. See "Gracefully exit a blocking read()"
                # in the inotify_simple documentation.

                #print("Waiting for inotify thread...")
                watch_thread.join()
                #print("Inotify thread finished.")
                pipe_inotify_abort_w.close()

        print(f"{remote}: websocket connection ended")

def background_inotify(watch_files, pipe_inotify_abort_r, websocket):
    # This has be to a separate thread, because the file websocket.socket
    # is done in yet another separate thread. I would have preferred a single
    # thread per websocket that uses select.select. Now, we have three threads
    # per websocket: the event processor thread of the websockets library,
    # the background_inotify thread and the connection's handle_connection
    # thread.

    inotify = inotify_simple.INotify()
    watch_flags = inotify_simple.flags.DELETE_SELF \
        | inotify_simple.flags.MODIFY \
        | inotify_simple.flags.MOVE_SELF
    for f in watch_files:
        #print(f"Watching for changes to file: {f}")
        inotify.add_watch(f, watch_flags)

    while True:
        readable, _, _ = select.select([inotify, pipe_inotify_abort_r], [], [])
        if pipe_inotify_abort_r in readable:
            break
        if inotify in readable:
            for m in inotify.read(timeout=0):
                websocket.send(json.dumps({'msg':'localmodule_changed'}))
                # Currently multiple localmodule_changed messages are
                # potentially sent to the client. Alternatively, the
                # background_inotify thread could terminate after the first
                # message.

    inotify.close()
    pipe_inotify_abort_r.close()


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
        self.tar_lock = threading.Lock()
        
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

            if req_path == Path('api/version'):
                return self.process_request_version()

            return self.process_request_static(req_path)
        except:
            print(traceback.print_exc())
            return build_response(http.HTTPStatus.INTERNAL_SERVER_ERROR)

    def process_request_example(self, name):
        src = ''
        srctype = 'Python'
        uistate = {}
        from .lib import examples
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

    def process_request_version(self):
        data = json.dumps({'version': version})
        return build_response(data=data.encode('utf8'), mime_type='application/json')

    def process_request_static(self, req_path):
        if not self.tar:
            return build_response(http.HTTPStatus.NOT_FOUND)
        
        # tarfile.TarFile seems not to be thread-safe, a semaphore seems to fix this.
        with self.tar_lock:
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

def main():
    parser = argparse.ArgumentParser(prog='ordec-server',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('-l', '--hostname', default="127.0.0.1", help="Hostname to listen on (default 127.0.0.1).")
    parser.add_argument('-p', '--port', default=8100, type=int, help="Port to listen on (default 8100).")
    parser.add_argument('-r', '--static-root', help="Path for static web resources. If not specified, the webdist.tar file included in the ORDeC installation is used.", nargs='?')
    parser.add_argument('-b', '--backend-only', action='store_true', help="Serve backend only. Requires a separate server (e.g. Vite) to serve the frontend.")
    parser.add_argument('-n', '--no-browser', action='store_true', help="Show URL, but do not launch browser.")
    parser.add_argument('-m', '--module', help="Open the specified module from the local file system (local mode).")
    parser.add_argument('-w', '--view', help="Open specified view of selected module (requires --module / local mode).")
    parser.add_argument('--url-authority', help="Use provided URL authority part (host:port) instead values of --hostname and --port for printed / opened URL.")
    parser.add_argument('-V', '--version', action='version', version=f'%(prog)s {version}')


    args = parser.parse_args()
    hostname = args.hostname
    port = args.port

    auth_token = secrets.token_urlsafe()

    if args.url_authority:
        user_url = f"http://{args.url_authority}"
    elif args.backend_only:
        user_url = f"http://localhost:5173"
        # Vite provides the frontend for the user on port 5173:
        print("--backend-only: Make sure to run separate frontend server using 'npm run dev' in web/, in addition to this 'ordec-server'.")
    else:
        user_url = f"http://{hostname}:{port}"

    if args.backend_only:
        static_handler = StaticHandler()
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

    if args.module:
        user_url += f"/app.html?auth={auth_token}&module={args.module}"
        if args.view:
            user_url += f"&view={args.view}"
        # Enable importing modules from current working directory:
        sys.path.append(os.getcwd()) 
    else:
        user_url += f"/?auth={auth_token}"

    # Launch server in separate daemon thread (daemon=True). The connection
    # threads automatically inherit the daemon property. All daemon threads
    # are terminated when the main thread terminates. This makes it possible
    # to terminate the whole thing with a single Ctrl+C.
    # A future version of the websockets library might make this workaround
    # unnecessary.
    threading.Thread(target=server_thread, args=(hostname, port, static_handler, auth_token), daemon=True).start()

    print(f"To start ORDeC, navigate to: {user_url}")

    if args.no_browser:
        launch_html = None
    else:
        time.sleep(1)
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
    c = ConnectionHandler(auth_token=auth_token, sysmodules_orig=sys.modules)
    with serve(c.handle_connection, hostname, port, process_request=static_handler.process_request) as server:
        #print(f"Listening on {hostname}, port {port}")
        server.serve_forever()
