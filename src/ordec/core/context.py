# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from contextvars import ContextVar, Token


_ctx_var = ContextVar("ctx", default=None)
_viewgen_ctx_var = ContextVar("viewgen_ctx", default=None)


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


class ViewBuilder:
    """
    Base view builder: per-view-type machinery around the root of the view
    being generated. Subclasses override to add capabilities (e.g. constraint
    solving).

    A ViewBuilder is created by the surrounding :class:`ViewGenContext`,
    either materialized from the viewgen's return annotation or adopting a
    root assigned via ``. = ...``.
    """
    def __init__(self, root):
        self.root = root

    @classmethod
    def create_root(cls, cell, root_cls):
        """
        Creates the root node for a view. Called when a @viewgen body's
        context is materialized from its return annotation.

        Args:
            cell: The Cell instance whose view is being generated.
            root_cls: The SubgraphRoot subclass to instantiate (e.g., Symbol,
                Schematic, Layout, SimHierarchy).

        Returns:
            A new SubgraphRoot instance initialized for the view type.
        """
        return root_cls()

    def setup(self):
        """
        Called after the view's NodeContext is entered. Overridden in
        subclasses to set up per-view machinery (e.g. constraint solvers).
        """
        pass

    def postprocess(self):
        """Override in subclasses to perform finalization on context exit."""
        pass

    def constrain(self, constraint):
        raise TypeError(f"Constraints not supported in {type(self.root).__name__} views.")

    def enter_group(self, group):
        """
        Called by ArrangementGroup.__enter__. Overridden in
        SchematicViewBuilder, the only builder supporting groups.
        """
        raise TypeError("Arrangement groups can only be used in a schematic viewgen.")

    def register_in_group(self, ref):
        """
        Records ref in the innermost active arrangement group.
        Only SchematicViewBuilder has groups.
        """
        pass

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
    Manages UnresolvedInstance state for view builders that support deferred
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
        # Mirror the ownership check of _entry(): nids are only unique per
        # subgraph, and a foreign entry (e.g. a Cell class instantiated
        # under a nested `with other.ctx():`) would silently never resolve.
        if inst.subgraph is not self.root.subgraph:
            raise TypeError(
                f"Cannot create unresolved instance {inst.full_path_label()}: "
                "it does not belong to the view of the running viewgen; "
                "instantiate the cell with its parameters instead."
            )
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
    Returns the running viewgen's view builder if it manages inst as a
    still-unresolved instance, else None.
    """
    vgctx = _viewgen_ctx_var.get()
    if not isinstance(vgctx, ViewGenContext):
        return None
    builder = vgctx.builder
    if not isinstance(builder, MixinUnresolvedInstances):
        return None
    if builder.unresolved_instance(inst) is None:
        return None
    return builder


class InstanceParams:
    """
    Write-only accessor for deferred instance parameters (``.$name = value``
    in ORD), returned by the ``params`` property of SchemInstance and
    LayoutInstance. Assignments are recorded in the active view builder
    until the instance is resolved.
    """
    def __init__(self, inst):
        self._inst = inst

    def __setattr__(self, name, value):
        if name.startswith("_"):
            return super().__setattr__(name, value)
        vgctx = _viewgen_ctx_var.get()
        builder = vgctx.builder if isinstance(vgctx, ViewGenContext) else None
        if not isinstance(builder, MixinUnresolvedInstances):
            raise TypeError(
                "Instance parameters can only be set inside a schematic or "
                "layout viewgen body."
            )
        builder.set_unresolved_param(self._inst, name, value)


class SymbolViewBuilder(ViewBuilder):
    @classmethod
    def create_root(cls, cell, root_cls):
        return root_cls(cell=cell)

    def postprocess(self):
        self.root.place_pins(vpadding=2, hpadding=2)


class SchematicViewBuilder(MixinUnresolvedInstances, ViewBuilder):
    def __init__(self, root):
        super().__init__(root)
        self.arrangement_groups = [] #: top-level arrangement groups, emitted in postprocess
        self.group_stack = [] #: arrangement groups whose body is currently executing

    def record_unresolved_conn(self, inst, here, path):
        """
        Records a connection of an unresolved instance's future pin (identified
        by path) to Net here. Flushed as SchemInstanceConn on resolution.
        """
        from .schema import Net, SchemPort
        # Validate the operand now so that a wiring mistake fails at the --
        # statement, as it does on resolved instances. This also keeps
        # _apply_resolution all-or-nothing: an invalid here operand would
        # only fail there after part of the conns have been inserted.
        if not isinstance(here, (Net, SchemPort)):
            raise TypeError(
                f"Cannot connect {type(here).__name__} to "
                f"{inst.full_path_label()}: the wire operand must be a "
                "Net or SchemPort."
            )
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

    def setup(self):
        from .constraints import Solver
        self.solver = Solver(self.root)

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


class LayoutViewBuilder(MixinUnresolvedInstances, ViewBuilder):
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

    def setup(self):
        from .constraints import Solver
        self.solver = Solver(self.root)

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


class SimulationViewBuilder(ViewBuilder):
    @classmethod
    def create_root(cls, cell, root_cls):
        if cell is None:
            raise TypeError(
                "Simulation views are built from a cell's schematic; a "
                "viewgen outside of a cell cannot generate one."
            )
        return root_cls.from_schematic(cell.schematic)


class ReportViewBuilder(ViewBuilder):
    pass


class ViewGenContext:
    """
    Per-call state of a running @viewgen body, held in _viewgen_ctx_var.

    The view builder (:attr:`builder`) is established lazily: materialized from
    the viewgen's return annotation when first needed, or adopted from a
    ``. = <root>`` assignment. This laziness is what lets an annotated
    viewgen still adopt its root (``-> DrcReport`` plus ``. = run_drc(...)``
    coexist): no root may be created until the body decides.
    """
    def __init__(self, cell, func):
        self.cell = cell
        self.func = func
        self.builder = None #: ViewBuilder; None until established
        self._node_ctx = None

    def _establish(self, builder):
        self._node_ctx = builder.root.ctx()
        self._node_ctx.__enter__()
        builder.setup()
        self.builder = builder
        return builder

    def require_builder(self):
        """
        Return the view builder, materializing it from the viewgen's return
        annotation if none is established yet.
        """
        if self.builder is not None:
            return self.builder
        root_cls = self.func.__annotations__.get('return')
        if root_cls is None:
            raise TypeError(
                f"viewgen {self.func.__qualname__} has no view root: assign "
                "one via `. = ...` or declare a view type annotation "
                "(`-> Schematic` etc.)."
            )
        try:
            builder_cls = root_cls.view_builder
        except AttributeError as e:
            raise TypeError(
                f"{root_cls!r} cannot be used as a viewgen return type."
            ) from e
        root = builder_cls.create_root(self.cell, root_cls)
        return self._establish(builder_cls(root))

    def adopt(self, root):
        """
        Make root the view root (the ``. = <root>`` path). The root must be
        mutable, as its NodeContext is entered for the rest of the body.
        """
        if self.builder is not None:
            raise TypeError(
                "view root is already established: `. = ...` can appear "
                "only once, before any node operation."
            )
        try:
            builder_cls = type(root).view_builder
        except AttributeError as e:
            raise TypeError(
                f"{type(root).__name__} cannot be adopted as a view root."
            ) from e
        self._establish(builder_cls(root))
        return root

    def close(self):
        if self._node_ctx is not None:
            self._node_ctx.__exit__(None, None, None)


class NoctxMarker:
    """
    Sentinel installed in _viewgen_ctx_var during @viewgen_noctx bodies, so that
    stray node operations error loudly instead of silently leaking into an
    outer viewgen's context.
    """

_noctx_marker = NoctxMarker()


def _noctx_error():
    return TypeError(
        "this operation requires a viewgen context; @viewgen_noctx installs "
        "none — use @viewgen."
    )


def require_viewgen_context():
    """
    Return the running @viewgen body's ViewGenContext, with friendly errors
    when there is none.
    """
    vgctx = _viewgen_ctx_var.get()
    if isinstance(vgctx, NoctxMarker):
        raise _noctx_error()
    if vgctx is None:
        raise TypeError("no view generator is currently running.")
    return vgctx


def current_node_context():
    """
    Return the NodeContext for relative (dotted) accesses. A pending @viewgen
    context is materialized first, so that node operations cannot leak into
    an outer viewgen's NodeContext.
    """
    vgctx = _viewgen_ctx_var.get()
    if isinstance(vgctx, ViewGenContext):
        if vgctx.builder is None:
            vgctx.require_builder()
    elif isinstance(vgctx, NoctxMarker):
        raise _noctx_error()
    return _ctx_var.get()


def run_viewgen_body(func, *args):
    """
    Run a @viewgen body: install the ViewGenContext, execute the body, and
    return the established context's root.

    The body must not return a value (the view is always the context root).
    On completion without an established root, the builder is materialized
    from the return annotation (yielding an empty view); without an
    annotation this is an error.
    """
    vgctx = ViewGenContext(args[0] if args else None, func)
    token = _viewgen_ctx_var.set(vgctx)
    try:
        ret = func(*args)
        if ret is not None:
            raise TypeError(
                f"viewgen {func.__qualname__} returned "
                f"{type(ret).__name__} instead of None; the view root "
                "comes from the view context. Use `. = ...` to assign "
                "it, or a bare `return` for an early exit."
            )
        if vgctx.builder is None:
            if func.__annotations__.get('return') is None:
                raise TypeError(
                    f"viewgen {func.__qualname__} produced no view: assign "
                    "a root via `. = ...` or declare a view type annotation."
                )
            vgctx.require_builder()
        vgctx.builder.postprocess()
        return vgctx.builder.root
    finally:
        _viewgen_ctx_var.reset(token)
        vgctx.close()


def run_noctx_body(func, *args):
    """
    Run a @viewgen_noctx body: install the sentinel (so stray node operations
    fail loudly instead of leaking into an outer viewgen's context) and
    return the body's return value, which must be the finished view.
    """
    token = _viewgen_ctx_var.set(_noctx_marker)
    try:
        ret = func(*args)
    finally:
        _viewgen_ctx_var.reset(token)
    if ret is None:
        raise TypeError(
            f"@viewgen_noctx {func.__qualname__} must return a view; it "
            "returned None."
        )
    return ret
