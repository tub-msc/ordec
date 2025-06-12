# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import sys
import os
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader
import ast

from .parser.parser import load_ord_from_string

# For related examples, see:
# - https://python.plainenglish.io/metapathfinders-or-how-to-change-python-import-behavior-a1cf3b5a13ec
# - https://github.com/madman-bob/python-custom-imports/

class OrdLoader(Loader):
    def __init__(self, ord_path):
        self.ord_path = ord_path

    def create_module(self, spec):
        try:
            with open(self.ord_path) as f:
                self.source_text = f.read()
        except:
            raise ImportError()

    def exec_module(self, module):
        module.__dict__['__file__'] = self.ord_path

        module.__dict__['ext'] = module. __dict__ # <-- TODO: bad hack, this is not how it is intended...
        
        exec("from ordec import Cell, Vec2R, Rect4R, Pin, PinArray, PinStruct, Symbol, Schematic, PinType, Rational as R, Rational, SchemPoly, SchemArc, SchemRect, SchemInstance, SchemPort, Net, Orientation, SchemConnPoint, SchemTapPoint, SimHierarchy, generate, helpers\nfrom ordec.sim2.sim_hierarchy import HighlevelSim", module.__dict__, module.__dict__)
        exec("from ordec.lib import Inv, Res, Gnd, Vdc, Idc, Nmos, Pmos, NoConn", module.__dict__, module.__dict__)

        exec("from ordec.parser.implicit_processing import symbol_process, preprocess, PostProcess, postprocess\nfrom ordec.parser.prelim_schem_instance import PrelimSchemInstance", module.__dict__, module.__dict__)


        python_source = ast.unparse(load_ord_from_string(self.source_text))        
        exec(python_source, module.__dict__, module.__dict__)

class OrdMetaPathFinder(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        mod_name = fullname.split(".")[-1]

        paths = path if path else [os.path.abspath(os.curdir)]

        for check_path in paths:
            ord_path = os.path.join(check_path, mod_name + ".ord")
            if os.path.exists(ord_path):
                return spec_from_loader(fullname, OrdLoader(ord_path))

        return None

# Register .ord loader globally:
sys.meta_path.append(OrdMetaPathFinder())
