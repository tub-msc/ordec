# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import sys
import os
import re
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader

from .ord2.parser import ord2topy
from .ord1.parser import ord2py

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
        def get_coding(path):
            # Get the coding string
            with open(path, 'r', encoding='utf-8') as f:
                line = f.readline()
                m = re.match(r'\s*#.*version\s*[:=]\s*([A-Za-z0-9_\-]+)', line)
                if m:
                    return m.group(1).lower()
                return None

        module.__dict__['__file__'] = self.ord_path
        coding = get_coding(self.ord_path)
        if coding == "ord2":
            code = compile(ord2topy(self.source_text), "<string>", "exec")
        elif coding == "ord1":
            code = compile(ord2py(self.source_text), "<string>", "exec")
        else:
            code = compile(ord2py(self.source_text), "<string>", "exec")
        exec(code, module.__dict__, module.__dict__)

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
