# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from .layout.read_gds import gds_discover
from .core import *

class ExtLibraryError(Exception):
    pass

class ExtLibrary:
    def __init__(self):
        self.layout_lambdas = {}

    def read_gds(self, gds_fn: str, layers: LayerStack):
        layout_lambdas_add = gds_discover(gds_fn, layers)
        for name in layout_lambdas_add.keys():
            if name in self.layout_lambdas:
                raise ExtLibraryError(f"Multiple layout sources found for cell {name!r}.")
        self.layout_lambdas |= layout_lambdas_add

    def __getitem__(self, name):
        return ExtLibraryCell(self, name)

class ExtLibraryCell(Cell):
    extlib = Parameter(ExtLibrary)
    name = Parameter(str)

    @generate
    def layout(self) -> Layout:
        print(f"generating layout {self.name}")
        try:
            layout_func = self.extlib.layout_lambdas[self.name]
        except KeyError:
            raise ExtLibraryError(f"No layout source found for cell {self.name!r}.") from None
        return layout_func()
