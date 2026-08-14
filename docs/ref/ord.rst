:mod:`ordec.ord` --- ORD language
=================================

ORD is ORDeC's current programming language. It offers full support of Python,
plus additional ORD syntax (a Python-superset) to improve textual IC design
within the ORDeC project. It currently focuses on simplifying schematic entry
and layout while also supporting regular Python syntax for simulations.
Execution of ORD code results in a one-pass compiler step that transforms the
input into context-based Python code.

This is only made possible by leveraging the power of
:class:`~ordec.core.context.ViewGenContext` and
:class:`~ordec.core.context.NodeContext`, which are explained in a later
paragraph. The actual ORD grammar is written in Lark. Lark is a well-known and
efficient Python parsing framework for grammars in EBNF form. The function call
:func:`ord_to_py` summarizes the necessary function calls for a proper
ORD-to-Python conversion. The conversion is mostly dependent on the
:class:`OrdTransformer` that inherits from :class:`PythonTransformer`. The
**PythonTransformer** is capable of transforming any Python code written in ORD
back to Python, and the **OrdTransformer** handles the conversion of the ORD
syntax. The following paragraphs summarize the logic behind the
ORD-to-Python conversion.


For a practical demonstration, please visit the ORD tutorial :ref:`ord_tutorial` page!


ORD to Python in Detail
-----------------------

ORD is not a general-purpose programming language. It is developed to simplify certain steps in IC design, especially for the ORDeC project. The entire backend of ORDeC is written in Python, but using Python for tasks like schematic entry can become complicated and cumbersome. ORD represents a more convenient syntax layer that makes structuring and describing IC designs much easier.

Mastering the ORD language requires understanding two crucial parts. First, the ORD language itself: what it offers and what it represents. Second, the converted code: understanding how ORD code is converted back to Python. This helps, especially if you run into trouble while programming or designing, and it also helps you understand how the project works under the hood. Especially for complex programs and debugging purposes, understanding the Python side can become important.

ORD Contexts
------------

The dotted syntax of ORD, which accesses the current context element, requires
having a reference to that element. This structure therefore necessitates that
statements and expressions inside a context block have a reference to the
parent even after transformation of ORD back to Python. This logic is
implemented with :class:`~ordec.core.context.ViewGenContext` for the running
viewgen and :class:`~ordec.core.context.NodeContext` for the currently active
node.
They use the Python ``with`` environment together with a context variable
:class:`ContextVar` to always maintain a reference without requiring
information about the parent during transformation. With ORD, we try to keep
the transformation logic as simple as possible and leverage the power of
Python to supply the necessary constructs during execution.

.. code-block::

    # Indented body
    port xyz:
        .pos=(1,2)
    # Inline body
    port xyz: .pos=(1,2)

Node Statements
^^^^^^^^^^^^^^^

A **node statement** is the ``A B`` construct that creates and names an element in the current context. There are three types of node statements:

1. **Node class statements** — the type is a Node subclass, e.g., ``LayoutRect x``
2. **Node instance statements** — the type is a Cell class or instance, e.g., ``Nmos x``
3. **Node keyword statements** — the type is a built-in keyword, e.g., ``input x``, ``output y``, ``port z``, ``net a``, ``path p``

The pin and port keywords come with direction-based align defaults: ``input``
pins face ``West``, ``output`` pins ``East``, and ``inout`` pins ``South``. A
``port`` defaults to the flipped align of its symbol pin, so e.g. a
West-facing input pin yields an East-facing port. An ``.align=`` assignment
in the statement body overrides these defaults. ``net`` and ``path`` create a
``Net`` or ``PathNode``, e.g. ``net clk: .auto_wire = False``.

A node statement may have an optional body (indented block after ``:``) for setting attributes:

.. code-block::

    Nmos pd:
        .$l = 400n

Or it can be bodyless:

.. code-block::

    Nmos pd

To demonstrate how the ORD context works and how the conversion from ORD to Python looks, consider the following example:

**ORD code**

.. code-block:: 

    cell Inv:
        viewgen symbol(self) -> Symbol:
            inout vdd: .align=North
            inout vss: .align=South
            input a: .align=West
            output y: .align=East

        viewgen schematic(self) -> Schematic:
            port vdd: .pos=(2,13); .align=North
            port vss: .pos=(2,1); .align=South
            port y: .pos=(9,7); .align=West
            port a: .pos=(1,7); .align=East

            Nmos pd:
                .s -- vss
                .b -- vss
                .d -- y
                .pos = (3,2)
                .$l = 400n
            Pmos pu:
                .s -- vdd
                .b -- vdd
                .d -- y
                .pos = (3,8)
                .$l = 400n

            for instance in pu, pd:
                instance.g -- a

**Compiled Python code**

.. note::

    The actual compiled code uses ``__ord_context__`` instead of ``context``
    (and ``__ordec_core__`` for core names such as the ``viewgen`` decorator)
    to avoid name collisions with user code. Here we use
    ``import ordec.ord.context as context`` for readability when calling helper
    functions such as ``add`` and ``root``.

.. admonition:: Changed behavior

    ``viewgen`` used to be written without a parameter list
    (``viewgen symbol -> Symbol:``), with the compiler defining an implicit
    ``self`` for viewgens placed inside a ``cell`` body. That syntax is now
    a hard syntax error (with a fix-it), because the implicit variable
    definition seemed at odds with Python's language design. Now the receiver
    is declared like in any Python ``def``, the translation is
    placement-independent, and the ``->`` annotation is now optional.

A viewgen statement declares its receiver explicitly: the parameter list is
mandatory, and the receiver parameter (conventionally named ``self``) binds
the cell instance when the viewgen is a cell attribute. The expression after
``->`` becomes the return annotation of the generated function. It is
optional, and it is usually a simple name such as ``Symbol`` or
``Schematic``, but it can be any ORD expression that evaluates to a view
target. Like standard Python annotations, it is evaluated at definition time.
The keyword is exact sugar: ``viewgen f(self) -> T: suite`` compiles to
``@viewgen def f(self) -> T: suite``, with the user's parameters verbatim.
The translation is context-free — the compiler does no placement analysis,
and whether the result is a view method or a plain view function follows
Python's ordinary lexical scoping, like ``def``.

Under :class:`~ordec.core.cell.viewgen`, the body populates an implicit view
root instead of returning one. The root is established lazily, in one of two
ways:

- **Adoption**: ``. = <root>`` makes a root built elsewhere (e.g. by
  ``run_drc()``) the view root. It must come before any node operation and
  can appear only once. Because adoption bypasses
  ``ViewBuilder.create_root()``, an adopted ``Schematic`` or ``Layout`` does
  not automatically reference the cell's symbol — set ``symbol=self.symbol``
  by hand where needed.
- **Materialization from the annotation**: the first node operation (or
  completion of the body, yielding an empty view) creates the root from the
  return annotation.

Adoption wins if it runs first, so an annotation and ``. = ...`` coexist:
``-> DrcReport`` stays inert when the body assigns the report itself. With
neither an established root nor an annotation, node operations and completion
raise ``TypeError``. As a style convention, annotate even where optional —
Sphinx and the web UI read the annotation.

After the body, postprocessing (such as constraint solving and auto-wiring)
runs and the root becomes the view. Consequently, a viewgen body never
returns the view itself: a bare ``return`` exits the body early, and
returning a value raises ``TypeError`` (like a value-returning ``__init__``).
Every node statement saves the created element as a local variable and, if
the statement has a body, opens a nested node context with ``node.ctx()``. The
dotted access is converted into ``context.root()``. Accesses outside the context are still possible
through the local variable. An access like this is visible in the ``for`` loop
of the example.

.. code-block:: python

    import ordec.ord.context as context
    from ordec.core import viewgen

    class Inv(Cell):
        @viewgen
        def symbol(self) -> Symbol:
            vdd = context.add(('vdd',), Pin(pintype=PinType.Inout, align=D4.South))
            with vdd.ctx():
                context.root().align = North
            vss = context.add(('vss',), Pin(pintype=PinType.Inout, align=D4.South))
            with vss.ctx():
                context.root().align = South
            a = context.add(('a',), Pin(pintype=PinType.In, align=D4.West))
            with a.ctx():
                context.root().align = West
            y = context.add(('y',), Pin(pintype=PinType.Out, align=D4.East))
            with y.ctx():
                context.root().align = East

        @viewgen
        def schematic(self) -> Schematic:
            vdd = context.add_port(('vdd',))
            with vdd.ctx():
                context.root().pos = (2,13)
                context.root().align = North
            vss = context.add_port(('vss',))
            with vss.ctx():
                context.root().pos = (2,1)
                context.root().align = South
            y = context.add_port(('y',))
            with y.ctx():
                context.root().pos = (9,7)
                context.root().align = West
            a = context.add_port(('a',))
            with a.ctx():
                context.root().pos = (1,7)
                context.root().align = East

            pd = context.add_element(('pd',), Nmos)
            with pd.ctx():
                context.root().s -- vss
                context.root().b -- vss
                context.root().d -- y
                context.root().pos = (3,2)
                context.root().params.l = R('400n')

            pu = context.add_element(('pu',), Pmos)
            with pu.ctx():
                context.root().s -- vdd
                context.root().b -- vdd
                context.root().d -- y
                context.root().pos = (3,8)
                context.root().params.l = R('400n')

            for instance in pu, pd:
                instance.g -- a

A ``viewgen`` does not have to live in a cell. Outside of a ``cell`` body — at
module level, or inside an ordinary function — it declares an **empty
parameter list** and the same decorator serves it as a plain cached function:
calling it evaluates the view once and caches the result on the generator
itself. Module-level viewgens appear in the web UI view list. Since there is
no cell, view targets that require a cell (such as ``SimHierarchy``) cannot
be generated, and a cell-less ``Schematic`` cannot declare ports (ports
connect to the cell symbol's pins):

.. code-block::

    viewgen inv_drc() -> DrcReport:
        . = ihp130.run_drc(inv.layout, variant="minimal")

The ``viewgen`` keyword and the :class:`~ordec.core.cell.viewgen_noctx`
decorator are two first-class protocols, not old and new: the keyword (sugar
for :class:`~ordec.core.cell.viewgen`) populates a context-managed root,
while ``@viewgen_noctx`` marks a plain function whose body builds and
returns the view itself — usable in ``.ord`` files too, since ORD is a
superset of Python. ``@viewgen_noctx`` installs no viewgen context, so a
stray node operation or ``. = ...`` in such a body raises instead of leaking
into an enclosing viewgen. See :doc:`cell_and_viewgen` for the decorators.

Whether a ``viewgen`` becomes a view method or a plain view function follows
Python's lexical binding rule for ``def`` — nothing more.


Anonymous Node Statements
^^^^^^^^^^^^^^^^^^^^^^^^^

Prepending a node statement with the ``anonymous`` keyword creates the node
**without** registering it in the ORDB path system.  The node is still assigned
to a local Python variable, so it can be referenced in subsequent code.  This
is useful inside loops or other situations where multiple nodes of the same type
would cause NPath name clashes:

.. code-block::

    for sd in (.m8.sd[1], .m7.sd[1]):
        anonymous LayoutRect r:
            .layer = layers.Metal1
        ! r.contains(sd.rect)

Without ``anonymous``, writing ``LayoutRect r`` twice (across loop iterations)
would attempt to register the path name ``r`` twice, causing a conflict.  With
``anonymous``, each iteration creates a fresh node that is only accessible
through the local variable ``r``.

Anonymous node statements support all the same forms as regular node statements:

.. code-block::

    # Bodyless
    anonymous Pin a

    # With body
    anonymous LayoutRect r:
        .layer = layers.Metal1

    # Multiple targets (bodyless only)
    anonymous Pin x, y, z

``anonymous`` is a **soft keyword**: it can still be used as a regular
identifier (variable name, function name, etc.) in all other contexts.

Internally, ``anonymous LayoutRect r`` compiles to
``r = context.add_element(None, LayoutRect)``.  When ``add`` receives ``None``
as the name tuple, it adds the node to the subgraph without creating an NPath
entry.


Connection Operator ``--``
^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``--`` operator connects an instance pin to a net (or vice versa).  It is
not a dedicated grammar rule but a **pseudo-operator** that relies on standard
Python parsing: ``a -- b`` is parsed as ``a - (-b)``, combining subtraction
(``__sub__``) and negation (``__neg__``).  Both operand orders are supported,
so ``inst.d -- vss`` and ``vss -- inst.d`` are equivalent.

Internally, the negation step returns a ``NegatedWireOperand`` and the
subtraction step detects this sentinel and calls ``__wire_op__`` to create the
actual connection. For resolved instances, this inserts a
``SchemInstanceConn`` node directly; for unresolved instances (created from a
Cell class, symbol not yet resolved), the connection is recorded in the view
context and inserted when the instance is resolved.

.. code-block::

    # These two forms are equivalent:
    inst.d -- vss      # pin -- net
    vss -- inst.d      # net -- pin

    # Python sees:  inst.d.__sub__(vss.__neg__())
    #          or:  vss.__sub__(inst.d.__neg__())  → fallback to _NegatedForWire.__rsub__

Because ``--`` is plain Python arithmetic, it coexists with regular numeric
expressions: ``2 -- 2`` evaluates to ``4`` as expected.


Constraint Statements ``!``
^^^^^^^^^^^^^^^^^^^^^^^^^^^

A statement starting with ``!`` declares a linear constraint instead of
executing a normal statement. The constraint is added to the view's own
:class:`~ordec.core.constraints.Solver`, which is solved automatically at the
end of the viewgen body. This is available in layout and schematic views (see
:mod:`ordec.core.constraints`):

.. code-block::

    with Col(gap=4) as stack:
        Pmos pu
        Nmos pd
    ! stack.southwest == (3, 1)

Internally, ``! expr`` compiles to ``context.constrain(expr)``, which forwards
the constraint to the running viewgen's view builder.


The following summary shows the most important functions and classes of ORD.
Please refer to the Python codebase for more background information and
details.


Parser
------

.. automodule:: ordec.ord

.. autofunction:: ordec.ord.parser.parse_with_errors
.. autofunction:: ordec.ord.parser.ord_to_py

Contexts
--------

.. autoclass:: ordec.core.context.NodeContext
    :members:

.. autoclass:: ordec.core.context.ViewGenContext
    :members:

.. autoclass:: ordec.core.context.ViewBuilder
    :members:

.. autoclass:: ordec.core.context.LayoutViewBuilder
    :members:

OrdTransformer
--------------

.. autoclass:: ordec.ord.ord_transformer.OrdTransformer
    :members:
    :show-inheritance:

PythonTransformer
-----------------

.. autoclass:: ordec.ord.python_transformer.PythonTransformer

Importing ``.ord`` Files and ``__pycache__``
--------------------------------------------

Importing a ``.ord`` module works exactly like importing a ``.py`` module:
``ordec.importer`` registers ``.ord`` as an additional source suffix in
Python's standard import machinery, so ``sys.path`` order, packages,
``importlib.reload()`` and friends behave as usual. A ``foo.py`` shadows a
``foo.ord`` in the same directory.

Like Python itself, ORDeC caches compiled ``.ord`` modules in ``__pycache__``
directories next to the source, so the ORD-to-Python transpilation runs only
once per source change. Cache files are named like
``demo.cpython-313.opt-ord.pyc`` (the ``ord`` tag keeps them distinct from
the cache of a shadowing ``demo.py``) and start with a header encoding
everything their validity depends on: the interpreter version, a hash of the
``.ord`` source (content-based, not mtime-based), the modification time of
the transpiler sources (so that editing the transpiler in a development
install invalidates the cache), and the ordec version. On any mismatch —
including an ordec upgrade — the module is transpiled from source again and
the cache file overwritten in place, so stale files do not accumulate.
Besides the compiled code, the cache stores the generated Python source, so
``__ord_py_source__`` is available on cache hits too.

The cache is meant to be fully transparent: writes are atomic, corrupt or
unreadable cache files are silently rewritten, a read-only source tree
disables caching, and it is always safe to delete ``__pycache__``
directories. The one knob is ``PYTHONDONTWRITEBYTECODE=1`` (or ``python
-B``, or setting ``sys.dont_write_bytecode = True``), which disables writing
cache files for ``.ord`` modules just as for ``.py`` modules. As in CPython,
existing valid cache files are still *read*; for a fully cache-free run
(e.g. when debugging the transpiler), delete the ``__pycache__`` directories
as well.
