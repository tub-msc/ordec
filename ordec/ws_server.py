# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
WebSocket server for use in conjunction with the new web interface.
"""
from . import Cell, Schematic, Symbol, View, SimHierarchy, SimNet
from .parser.parser import load_ord_from_string

import argparse
from websockets.sync.server import serve
from websockets.http11 import Request, Response
from websockets.datastructures import Headers
import http
import json
import traceback
import ast
from pathlib import Path
import mimetypes
from urllib.parse import urlparse

def build_cells(source_type: str, source_data: str) -> (dict, dict):
    conn_globals = {}
    conn_globals['ext'] = conn_globals # <-- bad hack, this is not how it is intended...
    exec("from ordec import Cell, Vec2R, Rect4R, Pin, PinArray, PinStruct, Symbol, Schematic, PinType, Rational as R, Rational, SchemPoly, SchemArc, SchemRect, SchemInstance, SchemPort, Net, Orientation, SchemConnPoint, SchemTapPoint, SimHierarchy, generate, helpers\nfrom ordec.sim2.sim_hierarchy import HighlevelSim", conn_globals, conn_globals)
    #exec("from ordec.lib.test import ResdivHierTb\nfrom ordec.lib import Ringosc, Inv, Res, Gnd, Vdc, Nmos, Pmos", conn_globals, conn_globals)
    exec("from ordec.lib import Inv, Res, Gnd, Vdc, Nmos, Pmos", conn_globals, conn_globals)

    if source_type == 'python' or source_type == 'ord':
        try:
            if source_type == 'ord':
                exec("from ordec.parser.implicit_processing import symbol_process, preprocess, PostProcess, postprocess\nfrom ordec.parser.prelim_schem_instance import PrelimSchemInstance", conn_globals, conn_globals)
                python_source = ast.unparse(load_ord_from_string(source_data))
            else:
                python_source = source_data
            exec(python_source, conn_globals, conn_globals)
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
                cell_views = [elem for elem in dir(v()) if (not elem.startswith('__')) and (not elem in ('children', 'instances', 'params', 'params_list'))]
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

def serialize_view(name, view):
    if not isinstance(view, View):
        return {'exception': "Requested object is not View."}

    if isinstance(view, (Schematic, Symbol)):
        from .render import render_svg
        return {'img': render_svg(view).as_url()}

    if isinstance(view, SimHierarchy):
        dc_table = []
        for sn in view.traverse(SimNet):
            if not sn.dc_voltage:
                continue
            dc_table.append([str(sn.path()[2:]), sn.dc_voltage])

        return {'dc_table': dc_table}

    # Fallback: just return the view as tree.
    return {'tree':view.tree()}

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


class MyStaticHandler:
    """
    This adds a static file HTTP server to the websockets HTTP server.
    This way, for local demos it is not needed to run two separate servers.
    For development or (possible future) multi-user production setups,
    this should not be used.
    """
    def __init__(self, static_root: Path):
        if static_root:
            self.static_root = Path(static_root).resolve()
        else:
            self.static_root = None

    def process_request(self, connection, request):
        url=urlparse(request.path)
        if url.path.startswith('/'):
            req_path = Path(url.path[1:])
        else:
            req_path = Path(url.path)

        if req_path == Path('websocket'):
            return None

        if self.static_root:
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

        return build_response(http.HTTPStatus.NOT_FOUND)

def main():
    parser = argparse.ArgumentParser(prog='ordec-server')
    parser.add_argument('-l', '--hostname', default="localhost", help="Hostname to listen on.")
    parser.add_argument('-p', '--port', default=8100, type=int, help="Port to listen on.")
    parser.add_argument('-r', '--static-root', help="Static web directory.", nargs='?')

    args = parser.parse_args()
    hostname = args.hostname
    port = args.port

    static_handler = MyStaticHandler(args.static_root)

    with serve(handle_connection, hostname, port, process_request=static_handler.process_request) as server:
        print(f"Listening on {hostname}, port {port}")
        server.serve_forever()
