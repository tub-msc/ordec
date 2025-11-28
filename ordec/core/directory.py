# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
from public import public
from .cell import Cell
from .schema import Symbol, Schematic, Layout
from .ordb import SubgraphRoot, Node
        
@public
class Directory:
    """
    Creates and maintains a set of unique names for cells and objects within
    subgraphs.

    For compatibility with case-insensitive tools, names are lowercase-only.
    Names contain only a-z, 0-9 and underscore (_) characters.
    """

    def __init__(self):
        self.obj_of_name = {}
        self.name_of_obj = {}
        self.subgraph_of_cell = {}

    def unique_name(self, basename, obj, domain=None):
        try:
            name = self.name_of_obj[obj]
        except KeyError:
            name = basename
            suffix = 0
            while (domain, name) in self.obj_of_name:
                name = f"{basename}{suffix}"
                suffix += 1
            self.obj_of_name[domain, name] = obj
            self.name_of_obj[obj] = name
            return name
        else:
            if not name.startswith(basename):
                raise ValueError(f"Existing name {name!r} does not match requested basename.")
            return name

    def name_subgraph(self, subgraph: Symbol|Schematic|Layout):
        if subgraph.cell is None:
            return self.unique_name(f"__subgraph{id(subgraph.subgraph):x}", subgraph)
        else:
            if (subgraph.cell, type(subgraph)) in self.subgraph_of_cell:
                if self.subgraph_of_cell[subgraph.cell, type(subgraph)] != subgraph:
                    raise Exception(f"Multiple subgraphs of type {type(subgraph)} associated with {subgraph.cell}.")
            else:
                self.subgraph_of_cell[subgraph.cell, type(subgraph)] = subgraph
            return self.name_cell(subgraph.cell)

    def subgraph_of_name(self, name: str, subgraph_type: type):
        cell_or_subgraph = self.obj_of_name[None, name]
        if isinstance(cell_or_subgraph, subgraph_type):
            return cell_or_subgraph
        elif isinstance(cell_or_subgraph, Cell):
            print(self.subgraph_of_cell)
            return self.subgraph_of_cell[cell_or_subgraph, subgraph_type]
        else:
            raise Exception("Could not find it!")

    def name_cell(self, cell: Cell):
        basename = cell.escaped_name().lower()
        return self.unique_name(basename, cell)

    def name_node(self, node: Node, prefix: str = ""):
        if not isinstance(node, Node):
            raise TypeError(f"Expected Node, got {node!r}.")

        if node.npath_nid is None:
            basename = f"__nid{node.nid}"
        else:
            basename = "_".join(node.full_path_list())
            basename = re.sub(r"[^a-zA-Z0-9]", "_", basename).lower()

        basename = prefix + basename

        return self.unique_name(basename, node, node.root)

    def existing_name_node(self, node: Node):
        """
        Similar to name_node, but requires the node to already be named. Prefix
        is not known. In this case, name_node could raise an Exception when prefix
        is left at the default "".
        """

        return self.name_of_obj[node]

        #if self.name_obj() # TODO

        # try:
        #     return self.layout_names[layout].encode('ascii')
        # except KeyError:
        #     if layout.cell is None:
        #         basename = f"__{id(layout.subgraph):x}"
        #     else:
        #         basename = layout.cell.escaped_name()
        #     name = basename
        #     suffix = 0
        #     while name in self.layout_names:
        #         name = f"{basename}_{suffix}"
        #         suffix += 1
        #     self.layout_names[layout] = name
        #     return name.encode('ascii')
