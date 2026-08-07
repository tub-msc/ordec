# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from contextvars import ContextVar, Token


_ctx_var = ContextVar("ctx", default=None)
_view_ctx_var = ContextVar("view_ctx", default=None)


class InstanceResolutionError(Exception):
    """
    Raised when an instance that should be resolved lacks its symbol or
    layout reference. Errors that occur while resolving (bad parameters,
    defective deferred wiring) raise their own exception types instead,
    annotated with the instance and its source location.
    """


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
        Creates the root node for a view. Called through create_view_context()
        during the setup phase of ORD viewgens.

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
        try:
            if exc_type is None:
                self.postprocess()
        finally:
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

    def register_unresolved(self, inst, cell_cls):
        # Should be unreachable: for view types without unresolved-instance
        # support, inserting the instance node fails on its in_subgraphs
        # check before add_element() reaches register_unresolved().
        raise TypeError(
            "Deferred cell instantiation is only supported in schematic "
            "and layout viewgens."
        )


class UnresolvedInstance:
    """
    Deferred state of an instance created from a Cell class (``MyCell x:``).
    The instance node exists in the subgraph, but its symbol/layout reference
    is unset until the parameters are complete. Parameters set via ``.$name``
    accumulate here (last assignment wins). Once any access requires the
    resolved sub-view, the instance is resolved; setting parameters
    afterwards raises.
    """
    def __init__(self, inst, cell_cls):
        self.inst = inst
        self.cell_cls = cell_cls
        self.params = {}
        self.conns = [] #: (here Net, path tuple) pairs; schematic contexts only
        self.resolved = False


class MixinUnresolvedInstances:
    """
    Manages UnresolvedInstance state for view contexts that support deferred
    cell instantiation (schematic and layout).
    """
    def __init__(self, root):
        super().__init__(root)
        self.unresolved_instances = {} #: nid -> UnresolvedInstance

    def _entry(self, inst):
        # The nid alone is ambiguous: a nested viewgen builds a different
        # subgraph whose nids can collide with ours.
        if inst.subgraph is not self.root.subgraph:
            return None
        return self.unresolved_instances.get(inst.nid)

    def unresolved_instance(self, inst):
        """
        Returns the still-unresolved UnresolvedInstance entry for inst, or
        None.
        """
        entry = self._entry(inst)
        if entry is None or entry.resolved:
            return None
        return entry

    def register_unresolved(self, inst, cell_cls):
        self.unresolved_instances[inst.nid] = UnresolvedInstance(inst, cell_cls)

    def set_unresolved_param(self, inst, name, value):
        entry = self._entry(inst)
        if entry is None:
            raise TypeError(
                f"Cannot set parameter {name!r} of {inst.full_path_label()}: "
                "the instance was created from a fully parametrized cell; "
                "pass parameters at instantiation instead."
            )
        if entry.resolved:
            raise TypeError(
                f"Cannot set parameter {name!r} of {inst.full_path_label()}: "
                "the instance was already resolved by an earlier access."
            )
        entry.params[name] = value

    def resolve_instance(self, inst):
        """
        Resolves inst from its recorded parameters. No-op if the instance
        was already resolved.
        """
        entry = self.unresolved_instance(inst)
        if entry is None:
            return
        try:
            self._apply_resolution(inst, entry)
        except Exception as e:
            loc = inst.src_loc
            e.add_note(
                f"While resolving instance {inst.full_path_label()}"
                + (f" ({loc.filename}:{loc.line}:{loc.column})" if loc else "")
            )
            raise
        entry.resolved = True

    def resolve_all_instances(self):
        for entry in list(self.unresolved_instances.values()):
            if not entry.resolved:
                self.resolve_instance(entry.inst)


def unresolved_instance_ctx(inst):
    """
    Returns the active view context if it manages inst as a still-unresolved
    instance, else None.
    """
    ctx = _view_ctx_var.get()
    if not isinstance(ctx, MixinUnresolvedInstances):
        return None
    if ctx.unresolved_instance(inst) is None:
        return None
    return ctx


class InstanceParams:
    """
    Write-only accessor for deferred instance parameters (``.$name = value``
    in ORD), returned by the ``params`` property of SchemInstance and
    LayoutInstance. Assignments are recorded in the active view context
    until the instance is resolved.
    """
    def __init__(self, inst):
        self._inst = inst

    def __setattr__(self, name, value):
        if name.startswith("_"):
            return super().__setattr__(name, value)
        ctx = _view_ctx_var.get()
        if not isinstance(ctx, MixinUnresolvedInstances):
            raise TypeError(
                "Instance parameters can only be set inside a schematic or "
                "layout viewgen body."
            )
        ctx.set_unresolved_param(self._inst, name, value)


class SymbolViewContext(ViewContext):
    @classmethod
    def create_root(cls, cell, root_cls):
        return root_cls(cell=cell)

    def postprocess(self):
        self.root.place_pins(vpadding=2, hpadding=2)


class SchematicViewContext(MixinUnresolvedInstances, ViewContext):
    def __init__(self, root):
        super().__init__(root)
        self.arrangement_groups = [] #: top-level arrangement groups, emitted in postprocess
        self.group_stack = [] #: arrangement groups whose body is currently executing

    def record_unresolved_conn(self, inst, here, path):
        """
        Records a connection of an unresolved instance's future pin (identified
        by path) to Net here. Flushed as SchemInstanceConn on resolution.
        """
        self.unresolved_instance(inst).conns.append((here, path))

    def _apply_resolution(self, inst, entry):
        from .schema import Pin, SchemInstanceConn
        from ..schematic.helpers import recursive_getitem, SchematicError
        # Resolve all pin paths before mutating anything: a failure must
        # leave the instance untouched, so that a retried resolution does
        # not re-insert conns from the aborted attempt.
        symbol = entry.cell_cls(**entry.params).symbol
        pins = []
        seen_nids = set()
        for here, path in entry.conns:
            pin = recursive_getitem(symbol, path)
            if not isinstance(pin, Pin):
                raise SchematicError(
                    f"Deferred connection path {path!r} on "
                    f"{inst.full_path_label()} did not resolve to a Pin."
                )
            if pin.nid in seen_nids:
                raise SchematicError(
                    f"Pin {pin.full_path_label()} of "
                    f"{inst.full_path_label()} is connected more than once."
                )
            seen_nids.add(pin.nid)
            pins.append((here, pin))
        inst.symbol = symbol
        for here, pin in pins:
            inst % SchemInstanceConn(here=here, there=pin)

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

    def _check_instances_resolved(self):
        from .schema import SchemInstance
        for inst in self.root.all(SchemInstance):
            if inst.symbol is None:
                raise InstanceResolutionError(
                    f"Instance {inst.full_path_label()} has no symbol: it "
                    "was created without one and never registered as an "
                    "unresolved instance."
                )

    def postprocess(self):
        from .arrange import emit_toplevel_groups

        # Resolve unresolved instances first: all parameters are final once the
        # body has run, and the rest of the pipeline (arrangement groups,
        # placement, wiring, checks) only deals with resolved instances.
        self.resolve_all_instances()
        self._check_instances_resolved()

        emit_toplevel_groups(self.arrangement_groups, self.solver)
        self.solver.solve(allow_undefined=True)

        self.root.place_unplaced_instances()
        self.root.place_ports() # Places ports whose pos is None.

        # No position should be None anymore: unplaced instances and ports
        # were placed above. auto_wire() and check() rely on this.
        assert not self.solver.undefined_attrs()

        self.root.auto_wire()
        self.root.check(add_conn_points=True, add_terminal_taps=True)


class LayoutViewContext(MixinUnresolvedInstances, ViewContext):
    def _apply_resolution(self, inst, entry):
        inst.ref = entry.cell_cls(**entry.params).layout

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
        from .schema import LayoutInstance, LayoutInstanceArray
        self.resolve_all_instances()
        for inst_type in (LayoutInstance, LayoutInstanceArray):
            for inst in self.root.all(inst_type):
                if inst.ref is None:
                    raise InstanceResolutionError(
                        f"Instance {inst.full_path_label()} has no layout "
                        "reference: it was created without one and never "
                        "registered as an unresolved instance."
                    )
        self.solver.solve()

    def constrain(self, constraint):
        self.solver.constrain(constraint)


class SimulationViewContext(ViewContext):
    @classmethod
    def create_root(cls, cell, root_cls):
        if cell is None:
            raise TypeError(
                "Simulation views are built from a cell's schematic; a "
                "viewgen outside of a cell cannot generate one."
            )
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
        try:
            if exc_type is None:
                if self.root is None:
                    raise TypeError(
                        "viewgen body must assign the view root via `.`.")
                self.postprocess()
        finally:
            _view_ctx_var.reset(self._token)

    def set_root(self, value):
        if self.root is not None:
            raise TypeError("view root assigned more than once via `.`.")
        self.root = value
