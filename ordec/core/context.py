# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from contextvars import ContextVar, Token


_ctx_var = ContextVar("ctx", default=None)
_view_ctx_var = ContextVar("view_ctx", default=None)


class NodeContext:
    """
    Class which represents the context where a specific
    ORDB element is alive and accessible via relative
    accesses (dotted notation)
    """

    def __init__(self, root):
        self.root = root

    def __enter__(self):
        """Enter context, set context variable and save parent"""
        self._token = _ctx_var.set(self)
        old = self._token.old_value
        self.parent = old if old is not Token.MISSING else None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and reset context variable"""
        _ctx_var.reset(self._token)


class ViewContext:
    """
    Base view context. Subclasses override to add capabilities (e.g. constraint
    solving).

    ViewContext is a separate context from the NodeContext but its __enter__
    and __exit__ methods also automatically enter and exit a corresponding
    NodeContext.
    """
    def __init__(self, root):
        self.root = root

    @classmethod
    def create_root(cls, cell, root_cls):
        """
        Creates the root node for a view. Called through create_view_root()
        during the setup phase of ORD viewgen methods.

        Args:
            cell: The Cell instance whose view is being generated.
            root_cls: The SubgraphRoot subclass to instantiate (e.g., Symbol,
                Schematic, Layout, SimHierarchy).

        Returns:
            A new SubgraphRoot instance initialized for the view type.
        """
        return root_cls()

    def __enter__(self):
        self._node_ctx = self.root.ctx()
        self._node_ctx.__enter__()
        self._token = _view_ctx_var.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.postprocess()
        _view_ctx_var.reset(self._token)
        self._node_ctx.__exit__(exc_type, exc_val, exc_tb)

    def postprocess(self):
        """Override in subclasses to perform finalization on context exit."""
        pass

    def constrain(self, constraint):
        raise TypeError(f"Constraints not supported in {type(self.root).__name__} views.")

    def enter_group(self, group):
        """
        Called by ArrangementGroup.__enter__. Overridden in
        SchematicViewContext, the only context supporting groups.
        """
        raise TypeError("Arrangement groups can only be used in a schematic viewgen.")

    def register_in_group(self, ref):
        """
        Records ref in the innermost active arrangement group.
        Only SchematicViewContext has groups.
        """
        pass

    def set_root(self, value):
        raise TypeError(
            f"Cannot assign the view root via `.` in "
            f"{type(self.root).__name__} views."
        )


class SymbolViewContext(ViewContext):
    @classmethod
    def create_root(cls, cell, root_cls):
        return root_cls(cell=cell)

    def postprocess(self):
        self.root.place_pins(vpadding=2, hpadding=2)


class SchematicViewContext(ViewContext):
    def __init__(self, root):
        super().__init__(root)
        self.arrangement_groups = [] #: top-level arrangement groups, emitted in postprocess
        self.group_stack = [] #: arrangement groups whose body is currently executing

    @classmethod
    def create_root(cls, cell, root_cls):
        # A symbol is optional: a cell may define a schematic without a
        # corresponding symbol viewgen (e.g. an empty schematic or testbench).
        # Check the class for a symbol viewgen without evaluating it.
        if hasattr(type(cell), 'symbol'):
            symbol = cell.symbol
        else:
            symbol = None
        return root_cls(cell=cell, symbol=symbol)

    def __enter__(self):
        super().__enter__()
        from .constraints import Solver
        self.solver = Solver(self.root)
        return self

    def constrain(self, constraint):
        self.solver.constrain(constraint)

    def enter_group(self, group):
        """
        Registers group with the innermost active group (or as a new
        top-level group) and makes it the innermost active group.
        """
        if self.group_stack:
            self.group_stack[-1].add(group)
        else:
            self.arrangement_groups.append(group)
        self.group_stack.append(group)

    def exit_group(self):
        self.group_stack.pop()

    def register_in_group(self, ref):
        if self.group_stack:
            self.group_stack[-1].add(ref)

    def postprocess(self):
        from .arrange import emit_toplevel_groups

        emit_toplevel_groups(self.arrangement_groups, self.solver)
        self.solver.solve(allow_undefined=True)

        self.root.place_unplaced_instances()
        self.root.resolve_instances() # (preserves nids)
        self.root.place_ports() # Places ports whose pos is None.

        # No position should be None anymore: unplaced instances and ports
        # were placed above. auto_wire() and check() rely on this.
        assert not self.solver.undefined_attrs()

        self.root.auto_wire()
        self.root.check(add_conn_points=True, add_terminal_taps=True)


class LayoutViewContext(ViewContext):
    @classmethod
    def create_root(cls, cell, root_cls):
        # A symbol is optional: a cell may define a layout without a
        # corresponding symbol viewgen (LayoutPins reference the symbol, so a
        # pin-less layout needs none). Check the class for a symbol viewgen
        # without evaluating it.
        if hasattr(type(cell), 'symbol'):
            symbol = cell.symbol
        else:
            symbol = None
        return root_cls(cell=cell, symbol=symbol)

    def __enter__(self):
        super().__enter__()
        from .constraints import Solver
        self.solver = Solver(self.root)
        return self

    def postprocess(self):
        self.solver.solve()

    def constrain(self, constraint):
        self.solver.constrain(constraint)


class SimulationViewContext(ViewContext):
    @classmethod
    def create_root(cls, cell, root_cls):
        return root_cls.from_schematic(cell.schematic)


class ReportViewContext(ViewContext):
    pass


class AssignableViewContext(ViewContext):
    """
    View context for views whose root subgraph is produced by the viewgen body
    itself and assigned via ``.`` (e.g. ``. = run_drc(self.layout)``), rather
    than being pre-created by the context.

    This is used for views like DRC/LVS reports, where an external tool
    generates the complete subgraph in one step. Because the root does not
    exist when the context is entered, no NodeContext is established and
    relative (dotted) accesses are unavailable; the body is expected to assign
    a finished subgraph.
    """
    @classmethod
    def create_root(cls, cell, root_cls):
        # The root is assigned within the viewgen body, not pre-created here.
        return None

    def __enter__(self):
        self._token = _view_ctx_var.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            if self.root is None:
                raise TypeError("viewgen body must assign the view root via `.`.")
            self.postprocess()
        _view_ctx_var.reset(self._token)

    def set_root(self, value):
        if self.root is not None:
            raise TypeError("view root assigned more than once via `.`.")
        self.root = value
