:mod:`ordec.ord2` --- ORD2 language
===================================

ORD2 is a programming language that offers full support of Python, plus additional ORD syntax (a *Python-superset*) to improve textual IC design within the ORDeC project. It currently focuses on simplifying the schematic entry phase, while also supporting the usual Python syntax for simulations or layouts. The language revision described in this file is called **ORD2**; it is a reworked version of the former **ORD1**, which had its own grammar and was not based on the Python language. Execution of ORD code results in a one-pass compiler step that transforms the input into context-based Python code. 
This is only made possible by leveraging the power of the :class:`Context`, which is explained in a later paragraph. The actual ORD grammar is written in Lark. Lark is a well-known and efficient Python parsing framework for grammars in EBNF form. The function call :func:`ord2_to_py` summarizes the necessary function calls for a proper ORD to Python conversion. The conversion is mostly dependent on the :class:`Ord2Transformer` that inherits from :class:`PythonTransformer`. The **PythonTransformer** is capable of transforming any Python code written in ORD back to Python, and the **Ord2Transformer** handles the conversion of the ORD syntax. The following paragraphs will summarize the logic behind the ORD to Python conversion. 


For a practical demonstration, please visit the ORD tutorial :ref:`ord_tutorial` page!


ORD2 to Python in detail
------------------------

ORD is not a general-purpose programming language. It is developed to simplify certain steps in IC design, especially for the ORDeC project. The entire backend of ORDeC is written in Python, but using Python for tasks like schematic entry can become complicated and cumbersome. ORD represents a more convenient syntax layer that makes structuring and describing IC designs much easier.

Mastering the ORD language requires understanding two crucial parts. First, the ORD language itself: what it offers and what it represents. Second, the converted code: understanding how ORD code is converted back to Python. This helps, especially if you run into trouble while programming or designing, and it also helps you understand how the project works under the hood. Especially for complex programs and debugging purposes, understanding the Python side can become important.

ORD2 Contexts
-------------

The dotted syntax of ORD, which accesses the parent element, requires having a reference to the parent element. This structure therefore necessitates that statements and expressions inside a context block have a reference to the parent even after transformation of ORD back to Python. This logic is implemented with the so-called :class:`Context`. It uses the Python `with` environment together with a context variable :class:`ContextVar` to always maintain a reference without requiring information about the parent during transformation. With ORD, we try to keep the transformation logic as simple as possible and leverage the power of Python to supply the necessary constructs during execution.

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
        viewgen symbol:
            inout vdd(.align=North)
            inout vss(.align=South)
            input a(.align=West)
            output y(.align=East)

        viewgen schematic:
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

    The actual compiled code uses ``__ord_context__`` instead of ``context`` to avoid name collisions with user code. Here we use ``import ordec.ord2.context as context`` for readability.

Every time a node statement (viewgen, port, or a schematic instance) is encountered, the element is saved as a local variable and a ``with`` context is opened. The dotted access is converted into ``context.root()``. If multiple dots are written prior to the identifier, the dots are converted to ``context.root()(.parent)*``. Accesses outside the context are still possible through the local variable. An access like this is visible in the for loop of the example.

.. code-block:: python

    import ordec.ord2.context as context

    class Inv(Cell):
        @generate
        def symbol(self) -> Symbol:
            with context.Context(Symbol(cell=self)):
                vdd = context.add(('vdd',), Pin(pintype=PinType.Inout))
                with context.Context(vdd):
                    context.root().align = North
                vss = context.add(('vss',), Pin(pintype=PinType.Inout))
                with context.Context(vss):
                    context.root().align = South
                a = context.add(('a',), Pin(pintype=PinType.In))
                with context.Context(a):
                    context.root().align = West
                y = context.add(('y',), Pin(pintype=PinType.Out))
                with context.Context(y):
                    context.root().align = East
                return context.root().postprocess()

        @generate
        def schematic(self) -> Schematic:
            with context.Context(Schematic(cell=self, symbol=self.symbol)):
                vss = context.add_port(('vss',))
                with context.Context(vss):
                    context.root().pos = (2,1)
                    context.root().align = South
                vdd = context.add_port(('vdd',))
                with context.Context(vdd):
                    context.root().pos = (2,13)
                    context.root().align = North
                y = context.add_port(('y',))
                with context.Context(y):
                    context.root().pos = (9,7)
                    context.root().align = West
                a = context.add_port(('a',))
                with context.Context(a):
                    context.root().pos = (1,7)
                    context.root().align = East

                pd = context.add(('pd',), SchemInstanceUnresolved(resolver = lambda **params: Nmos(**params).symbol))
                with context.Context(pd):
                    context.root().s.__wire_op__(vss.ref)
                    context.root().b.__wire_op__(vss.ref)
                    context.root().d.__wire_op__(y.ref)
                    context.root().pos = (3,2)
                    context.root().params.l = R('400n')

                pu = context.add(('pu',), SchemInstanceUnresolved(resolver = lambda **params: Pmos(**params).symbol))
                with context.Context(pu):
                    context.root().s.__wire_op__(vdd.ref)
                    context.root().b.__wire_op__(vdd.ref)
                    context.root().d.__wire_op__(y.ref)
                    context.root().pos = (3,8)
                    context.root().params.l = R('400n')

                for instance in pu, pd:
                    instance.g.__wire_op__(a.ref)
                return context.root().postprocess()


The following summary shows the most important functions and classes of ORD2. Please refer to the Python codebase for more background information and details.


Parser
------

.. automodule:: ordec.ord2

.. autofunction:: ordec.ord2.parser.parse_with_errors
.. autofunction:: ordec.ord2.parser.ord2_to_py

Context
-------

.. autoclass:: ordec.ord2.context.Context
    :members:

OrdTransformer
--------------

.. autoclass:: ordec.ord2.ord2_transformer.Ord2Transformer
    :members:
    :show-inheritance:

PythonTransformer
-----------------

.. autoclass:: ordec.ord2.python_transformer.PythonTransformer
