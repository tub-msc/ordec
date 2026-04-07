:mod:`ordec.ord` --- ORD language
=================================

ORD is ORDeC's current programming language. It offers full support of Python,
plus additional ORD syntax (a Python-superset) to improve textual IC design
within the ORDeC project. It currently focuses on simplifying schematic entry
and layout while also supporting regular Python syntax for simulations.
Execution of ORD code results in a one-pass compiler step that transforms the
input into context-based Python code.

This is only made possible by leveraging the power of
:class:`~ordec.core.context.ViewContext` and
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

The dotted syntax of ORD, which accesses the parent element, requires having a
reference to the parent element. This structure therefore necessitates that
statements and expressions inside a context block have a reference to the
parent even after transformation of ORD back to Python. This logic is
implemented with :class:`~ordec.core.context.ViewContext` for the active view
and :class:`~ordec.core.context.NodeContext` for the currently active node.
They use the Python ``with`` environment together with a context variable
:class:`ContextVar` to always maintain a reference without requiring
information about the parent during transformation. With ORD, we try to keep
the transformation logic as simple as possible and leverage the power of
Python to supply the necessary constructs during execution.

.. code-block::

    # Type 1
    port xyz:
        .pos=(1,2)
    # Type 2
    port xyz(.pos=(1,2))

Node Statements
^^^^^^^^^^^^^^^

A **node statement** is the ``A B`` construct that creates and names an element in the current context. There are three types of node statements:

1. **Node class statements** — the type is a Node subclass, e.g., ``LayoutRect x``
2. **Node instance statements** — the type is a Cell class or instance, e.g., ``Nmos x``
3. **Node keyword statements** — the type is a built-in keyword, e.g., ``input x``, ``output y``, ``port z``

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
        viewgen symbol -> Symbol:
            inout vdd(.align=North)
            inout vss(.align=South)
            input a(.align=West)
            output y(.align=East)

        viewgen schematic -> Schematic:
            port vdd(.pos=(2,13); .align=North)
            port vss(.pos=(2,1); .align=South)
            port y (.pos=(9,7); .align=West)
            port a (.pos=(1,7); .align=East)

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

    The actual compiled code uses ``__ord_context__`` instead of ``context`` to
    avoid name collisions with user code. Here we use
    ``import ordec.ord.context as context`` for readability when calling helper
    functions such as ``add`` and ``root``.

At the start of a view generator, the compiler creates ``__ord_root__`` and
opens the root view context with ``__ord_root__.view_context(__ord_root__)``.
Every node statement then saves the created element as a local variable and, if
the statement has a body, opens a nested node context with ``node.ctx()``. The
dotted access is converted into ``context.root()``. If multiple dots are
written prior to the identifier, the dots are converted to
``context.root()(.parent)*``. Accesses outside the context are still possible
through the local variable. An access like this is visible in the ``for`` loop
of the example.

.. code-block:: python

    import ordec.ord.context as context

    class Inv(Cell):
        @generate
        def symbol(self) -> Symbol:
            __ord_root__ = Symbol(cell=self)
            with __ord_root__.view_context(__ord_root__):
                vdd = context.add(('vdd',), Pin(pintype=PinType.Inout))
                with vdd.ctx():
                    context.root().align = North
                vss = context.add(('vss',), Pin(pintype=PinType.Inout))
                with vss.ctx():
                    context.root().align = South
                a = context.add(('a',), Pin(pintype=PinType.In))
                with a.ctx():
                    context.root().align = West
                y = context.add(('y',), Pin(pintype=PinType.Out))
                with y.ctx():
                    context.root().align = East
            return __ord_root__.postprocess()

        @generate
        def schematic(self) -> Schematic:
            __ord_root__ = Schematic(cell=self, symbol=self.symbol)
            with __ord_root__.view_context(__ord_root__):
                vss = context.add_port(('vss',))
                with vss.ctx():
                    context.root().pos = (2,1)
                    context.root().align = South
                vdd = context.add_port(('vdd',))
                with vdd.ctx():
                    context.root().pos = (2,13)
                    context.root().align = North
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
            return __ord_root__.postprocess()


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
actual connection node (``SchemInstanceConn`` or
``SchemInstanceUnresolvedConn``).

.. code-block::

    # These two forms are equivalent:
    inst.d -- vss      # pin -- net
    vss -- inst.d      # net -- pin

    # Python sees:  inst.d.__sub__(vss.__neg__())
    #          or:  vss.__sub__(inst.d.__neg__())  → fallback to _NegatedForWire.__rsub__

Because ``--`` is plain Python arithmetic, it coexists with regular numeric
expressions: ``2 -- 2`` evaluates to ``4`` as expected.


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

.. autoclass:: ordec.core.context.ViewContext
    :members:

.. autoclass:: ordec.core.context.LayoutViewContext
    :members:

OrdTransformer
--------------

.. autoclass:: ordec.ord.ord_transformer.OrdTransformer
    :members:
    :show-inheritance:

PythonTransformer
-----------------

.. autoclass:: ordec.ord.python_transformer.PythonTransformer
