# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import re
from public import public
from .cell import Cell
from .schema import Symbol, Schematic, Layout
from .ordb import SubgraphRoot, Node
from collections.abc import Hashable
from typing import Optional

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

    def unique_name(self, basename: str, obj: Hashable, domain: Optional[Hashable]) -> str:
        """
        Returns a name for obj which is unique within the given domain.
        Args:
            basename: Used as starting point for finding a unique name.
                If this name is still available within the domain, it will be
                returned. Else, numbers are appended to make it unique.
            obj: The object to name.
            domain: The context in which the name must be unique.
                For top-level objects like cells or subgraphs, domain is
                typically None. For nodes within a subgraph, domain is typically
                the root of the subgraph.
        """
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

    def name_subgraph(self, subgraph: Symbol|Schematic|Layout) -> str:
        """
        If the subgraph has an associated cell, the unique name of that cell is
        returned. Otherwise, a unique name of the subgraph is returned.
        """
        if subgraph.cell is None:
            return self.unique_name(f"__subgraph{id(subgraph.subgraph):x}", subgraph, None)
        else:
            if (subgraph.cell, type(subgraph)) in self.subgraph_of_cell:
                if self.subgraph_of_cell[subgraph.cell, type(subgraph)] != subgraph:
                    raise Exception(f"Multiple subgraphs of type {type(subgraph)} associated with {subgraph.cell}.")
            else:
                self.subgraph_of_cell[subgraph.cell, type(subgraph)] = subgraph
            return self.name_cell(subgraph.cell)

    def subgraph_of_name(self, name: str, subgraph_type: type) -> 'Subgraph':
        """
        This method returns the subgraph of type subgraph_type for the requested
        top-level name. If the top-level name points to a subgraph of
        subgraph_type, it is returned. Otherwise, the top-level name might point
        to a cell that has has an associated subgraph of subgraph_type. If this
        is the case, that subgraph is returned.
        """
        cell_or_subgraph = self.obj_of_name[None, name]
        if isinstance(cell_or_subgraph, subgraph_type):
            return cell_or_subgraph
        elif isinstance(cell_or_subgraph, Cell):
            return self.subgraph_of_cell[cell_or_subgraph, subgraph_type]
        else:
            raise Exception(f"Could not find {subgraph_type!r} of {name!r}.")

    def name_cell(self, cell: Cell) -> str:
        basename = cell.escaped_name().lower()
        return self.unique_name(basename, cell, None)

    def name_node(self, node: Node, prefix: str = "") -> str:
        """
        Returns a name for node that is unique within its subgraph. The name
        will start with the given prefix.
        """
        if not isinstance(node, Node):
            raise TypeError(f"Expected Node, got {node!r}.")

        if node.npath_nid is None:
            basename = f"__nid{node.nid}"
        else:
            basename = "_".join(node.full_path_list())
            basename = re.sub(r"[^a-zA-Z0-9]", "_", basename).lower()

        basename = prefix + basename

        return self.unique_name(basename, node, node.root)

    def existing_name_node(self, node: Node) -> str:
        """
        This method is similar to name_node but has no prefix argument. It can
        only be used to retrieve the name of a node that has previously been
        named using name_node. In contrast to name_node, existing_name_node will
        return the node name with the previously chosen prefix and not
        enforce a specified prefix.
        """

        return self.name_of_obj[node]

    def node_of_name(self, root: SubgraphRoot, name: str) -> Node:
        return self.obj_of_name[root, name]
