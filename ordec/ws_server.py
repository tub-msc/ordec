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
import re
import traceback
import ast
from pathlib import Path
import mimetypes
from urllib.parse import urlparse
import threading
import signal
import importlib.resources
import tarfile

from .base import *
from .render import render
from .ordb import Subgraph
from .parser.parser import ord2py

def build_cells(source_type: str, source_data: str) -> (dict, dict):
    conn_globals = {}
    if source_type == 'python' or source_type == 'ord':
        try:
            if source_type == 'ord':
                code = ast.unparse(ord2py(source_data))
                #code = compile(ord2py(source_data), "<string>", "exec") <-- TODO: Not working at the moment.
                exec(code, conn_globals, conn_globals)
            else:
                exec(source_data, conn_globals, conn_globals)
        except Exception:
            print("Reporting exception.")
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
            print(f"Reporting {len(views)} views.")
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
        msg_ret |= serialize_view(view_name, view)
    except Exception:    
        msg_ret['exception'] = traceback.format_exc()

    return msg_ret

def fmt_float(val, unit):
    x=str(Rational(f"{val:.03e}"))+unit
    x=re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", x)
    x=x.replace("u", "μ")
    x=re.sub(r"e([+-]?[0-9]+)", r"×10<sup>\1</sup>", x)
    return x

def serialize_view(name, view):
    if not isinstance(view, Subgraph):
        return {'exception': "Requested object is not View."}

    if isinstance(view.node, (Schematic, Symbol)):
        return {'html': render(view).svg().decode('ascii')}

    if isinstance(view.node, SimHierarchy):
        dc_voltages = []
        for sn in view.all(SimNet):
            if not sn.dc_voltage:
                continue
            dc_voltages.append([sn.full_path_str(), fmt_float(sn.dc_voltage, "V")])
        dc_currents = []
        for sn in view.all(SimInstance):
            if not sn.dc_current:
                continue
            dc_currents.append([sn.full_path_str(), fmt_float(sn.dc_current, "A")])
        return {'dc_voltages': dc_voltages, 'dc_currents': dc_currents}

    # Fallback: just return the view as tree.
    return {'tree':view.tables()}

def handle_connection(websocket):
    remote = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    print(f"{remote}: new connection")
    msgs = iter(websocket)

    # First message - read design input / build cells:
    msg_first = json.loads(next(msgs))
    assert msg_first['msg'] == 'source'
    source_type = msg_first['source_type']
    source_data = msg_first['source_data']
    print(f"Received source of type {source_type}.")
    msg_ret, conn_globals = build_cells(source_type, source_data)
    websocket.send(json.dumps(msg_ret))
    if not conn_globals:
        return

    for msg_raw in websocket:
        msg = json.loads(msg_raw)
        assert msg['msg'] == 'getview'
        view_name = msg['view']
        print(f"View {view_name} was requested.")

        msg_ret = query_view(view_name, conn_globals)
        websocket.send(json.dumps(msg_ret))
    print(f"{remote}: connection ended")

def build_response(status: http.HTTPStatus=http.HTTPStatus.OK, mime_type: str='text/plain', data: bytes=None):
    if data == None:
        data = status.name.encode("ascii")
    return Response(
        int(status),
        status.name,
        Headers(**{"Content-Type": mime_type, "Content-Length": str(len(data)), }),
        data,
    )

class StaticHandlerBase:
    """
    This adds a static file HTTP server to the websockets HTTP server.
    This way, for local demos it is not needed to run two separate servers.
    For development or (possible future) multi-user production setups,
    this should not be used.
    """
        
    def process_request(self, connection, request):
        url=urlparse(request.path)
        if url.path.startswith('/'):
            req_path = Path(url.path[1:])
        else:
            req_path = Path(url.path)

        if req_path == Path('websocket'):
            return None

        return self.process_request_static(connection, request, req_path)

    def process_request_static(self, connection, request, req_path):
        return build_response(http.HTTPStatus.NOT_FOUND)

class StaticHandlerDir(StaticHandlerBase):
    """
    This adds a static file HTTP server to the websockets HTTP server.
    This way, for local demos it is not needed to run two separate servers.
    For development or (possible future) multi-user production setups,
    this should not be used.
    """
    def __init__(self, static_root: Path):
        self.static_root = Path(static_root).resolve()
    
    def process_request_static(self, connection, request, req_path):
        requested_file = (self.static_root / req_path).resolve()
        if self.static_root != requested_file and (self.static_root not in requested_file.parents):
            # Catch path traversal:
            return build_response(http.HTTPStatus.FORBIDDEN)

        if requested_file.is_dir():
            requested_file = requested_file / 'index.html'
        try:
            mime_type = mimetypes.types_map[requested_file.suffix]
        except KeyError:
            mime_type = 'application/octet-stream'
        try:
            data = requested_file.read_bytes()
        except FileNotFoundError:
            return build_response(http.HTTPStatus.NOT_FOUND)
        except:
            print(traceback.print_exc())
            return build_response(http.HTTPStatus.INTERNAL_SERVER_ERROR)
        else:
            return build_response(http.HTTPStatus.OK, mime_type=mime_type, data=data)

def tar_path(p: Path) -> str:
    if len(p.parts) == 0:
        return '.'
    else:
        return f'./{p}'

class StaticHandlerTar(StaticHandlerBase):
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

    def __init__(self, fn: Path):
        self.tar = tarfile.open(fn)
        self.tar_semaphore = threading.Semaphore()

    def process_request_static(self, connection, request, req_path):
        url=urlparse(request.path)
        if url.path.startswith('/'):
            req_path = Path(url.path[1:])
        else:
            req_path = Path(url.path)

        if req_path == Path('websocket'):
            return None

        requested_file = Path(req_path)
        
        # tarfile.TarFile seems not to be thread-safe, a semaphore seems to fix this.
        with self.tar_semaphore:
            try:
                info = self.tar.getmember(tar_path(requested_file))
                if info.type == tarfile.DIRTYPE:
                    requested_file = requested_file / 'index.html'
                    info = self.tar.getmember(tar_path(requested_file))
            except KeyError:
                return build_response(http.HTTPStatus.NOT_FOUND)

            data = self.tar.extractfile(info).read()

        try:
            mime_type = mimetypes.types_map[requested_file.suffix]
        except KeyError:
            mime_type = 'application/octet-stream'

        return build_response(http.HTTPStatus.OK, mime_type=mime_type, data=data)

def main():
    parser = argparse.ArgumentParser(prog='ordec-server')
    parser.add_argument('-l', '--hostname', default="localhost", help="Hostname to listen on.")
    parser.add_argument('-p', '--port', default=8100, type=int, help="Port to listen on.")
    parser.add_argument('-r', '--static-root', help="Static web directory.", nargs='?')
    parser.add_argument('-n', '--no-frontend', action='store_true')

    args = parser.parse_args()
    hostname = args.hostname
    port = args.port
    
    if args.no_frontend:
        static_handler = StaticHandlerBase()
    else:
        if args.static_root:
            static_handler = StaticHandlerDir(args.static_root)
        else:
            webdist_tar = importlib.resources.files(__package__) / 'webdist.tar'
            static_handler = StaticHandlerTar(webdist_tar)

    # Launch server in separate daemon thread (daemon=True). The connection
    # threads automatically inherit the daemon property. All daemon threads
    # are terminated when the main thread terminates. This makes it possible
    # to terminate the whole thing with a single Ctrl+C.
    # A future version of the websockets library might make this workaround
    # unnecessary.
    threading.Thread(target=server_thread, args=(hostname, port, static_handler), daemon=True).start()

    try:
        while True:
            signal.pause()
    except KeyboardInterrupt:
        print("Terminating.")

def server_thread(hostname, port, static_handler):
    with serve(handle_connection, hostname, port, process_request=static_handler.process_request) as server:
        print(f"Listening on {hostname}, port {port}")
        server.serve_forever()
