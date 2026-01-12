:mod:`ordec.ord2` --- ORD2 language reference
=============================================

ORD2 is a programming language that offers full support of Python, plus additional ORD syntax (a *Python-superset*) to improve textual IC design within the ORDeC project. It currently focuses on simplifying the schematic entry phase, while also supporting the usual Python syntax for simulations or layouts. The language revision described in this file is called **ORD2**, it is a reworked version of the former **ORD1** which had its own grammar and was not based on the Python language. Execution of ORD code results in a one-pass compiler step which transforms the input into context-based Python code. 
This is only made possible by leveraging the power of the :class:`OrdContext` which is explained in a later paragraph. The actual ORD grammar is written in Lark. Lark is a well-known and efficient Python parsing framework for grammars in EBNF form. The function call :func:`ord2_to_py` summarizes the necessary function calls for a proper ORD to Python conversion. The conversion is mostly dependent on the :class:`Ord2Transformer` that inherits from :class:`PythonTransformer`. The **PythonTransformer** is capable of transforming any Python code written in ORD back to Python and the **Ord2Transformer** handles the conversion of the ORD syntax. The following paragraphs will summarize the logic behind the ORD to Python conversion. 


For a practical demonstration, please visit the ORD tutorial :ref:`ord_tutorial` page!


ORD2 to Python in detail
------------------------

ORD is not a general-purpose programming language. It is developed to simplify certain steps in IC design, especially for the ORDeC project. The entire backend of ORDeC is written in Python, but using Python for tasks like schematic entry can become complicated and cumbersome. ORD represents a more convenient syntax layer that makes structuring and describing IC designs much easier.

Mastering the ORD language requires understanding two crucial parts. First, the ORD language itself: what it offers and what it represents. Second, the converted code: understanding how ORD code is converted back to Python. This helps, especially if you run into trouble while programming or designing, and it also helps you understand how the project works under the hood. Especially for complex programs and debugging purposes, understanding the Python side can become important.

ORD2 Contexts
-------------

The dotted syntax of ORD, which accesses the parent element, requires having a reference to the parent element. This structure therefore necessitates that statements and expressions inside a context block have a reference to the parent even after transformation of ORD back to Python. This logic is implemented with the so-called :class:`OrdContext`. It uses the Python `with` environment together with a context variable :class:`ContextVar` to always maintain a reference without requiring information about the parent during transformation. With ORD, we try to keep the transformation logic as simple as possible and leverage the power of Python to supply the necessary constructs during execution.

.. code-block::

	# Type 1
	port xyz:
		.pos=(1,2)
	# Type 2
	port xyz(.pos=(1,2)

To demonstrate how the ORD context works and how the conversion from ORD to Python looks, consider the following two examples. Every time a context element (viewgen, port, or a schematic instance) is defined, the element is saved as a local variable `ctx` and a `with` context is opened. The dotted
access is converted into `ctx.root`. If multiple dots are written prior to the identifier, the dots are
converted to `ctx.root(.parent)*`. Accesses outside the context are still possible through the local variable. An access like this is visible in the for loop. 

**ORD code**

.. code-block:: 

	cell Inv:
	    viewgen symbol:
	        inout vdd(.align=Orientation.North)
	        inout vss(.align=Orientation.South)
	        input a(.align=Orientation.West)
	        output y(.align=Orientation.East)

	    viewgen schematic:
	        port vdd(.pos=(2,13); .align=Orientation.North)
	        port vss(.pos=(2,1); .align=Orientation.South)
	        port y (.pos=(9,7); .align=Orientation.West)
	        port a (.pos=(1,7); .align=Orientation.East)

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

.. code-block:: python

	class Inv(Cell):
	    @generate
	    def symbol(self) -> Symbol:
	        with OrdContext(root=Symbol(cell=self), parent=self):
	            vdd = ctx.add(('vdd',), Pin(pintype=PinType.Inout))
	            with OrdContext(root=vdd):
	                ctx.root.align = Orientation.North
	            vss = ctx.add(('vss',), Pin(pintype=PinType.Inout))
	            with OrdContext(root=vss):
	                ctx.root.align = Orientation.South
	            a = ctx.add(('a',), Pin(pintype=PinType.In))
	            with OrdContext(root=a):
	                ctx.root.align = Orientation.West
	            y = ctx.add(('y',), Pin(pintype=PinType.Out))
	            with OrdContext(root=y):
	                ctx.root.align = Orientation.East
	            return ctx.symbol_postprocess()

	    @generate
	    def schematic(self) -> Schematic:
	        with OrdContext(root=Schematic(cell=self, symbol=self.symbol), parent=self):
	            vss = ctx.add_port(('vss',))
	            with OrdContext(root=vss):
	                ctx.root.pos = (2,1)
	                ctx.root.align = Orientation.South
	            vdd = ctx.add_port(('vdd',))
	            with OrdContext(root=vdd):
	                ctx.root.pos = (2,13)
	                ctx.root.align = Orientation.North
	            y = ctx.add_port(('y',))
	            with OrdContext(root=y):
	                ctx.root.pos = (9,7)
	                ctx.root.align = Orientation.West
	            a = ctx.add_port(('a',))
	            with OrdContext(root=a):
	                ctx.root.pos = (1,7)
	                ctx.root.align = Orientation.East
	      
	            pd = ctx.add(('pd',), SchemInstanceUnresolved(resolver = lambda **params: Nmos(**params).symbol))
	            with OrdContext (root=pd):
	                ctx.root.s.__wire_op__(vss.ref)
	                ctx.root.b.__wire_op__(vss.ref)
	                ctx.root.d.__wire_op__(y.ref)
	                ctx.root.pos = (3,2)
	                ctx.root.params.l = R('400n')

	            pu = ctx.add(('pu',), SchemInstanceUnresolved(resolver = lambda **params: Pmos(**params).symbol))
	            with OrdContext (root=pu):
	                ctx.root.s.__wire_op__(vdd.ref)
	                ctx.root.b.__wire_op__(vdd.ref)
	                ctx.root.d.__wire_op__(y.ref)
	                ctx.root.pos = (3,8)
	                ctx.root.params.l = R('400n')
	                
	            for instance in pu, pd:
	                instance.g.__wire_op__(a.ref)
	            return ctx.schematic_postprocess()


The following summary shows the most important functions and classes of ORD2. Please refer to the Python codebase for more background information and details


Parser
------

.. automodule:: ordec.ord2

.. autofunction:: parse_with_errors
.. autofunction:: ord2_to_py

OrdContext
----------

.. autoclass:: OrdContext
	:members: 

OrdTransformer
--------------

.. autoclass:: Ord2Transformer
	:members:
	:show-inheritance:

PythonTransformer
-----------------

.. autoclass:: PythonTransformer
