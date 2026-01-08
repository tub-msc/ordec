:mod:`ordec.ord2` --- ORD2 language reference
=============================================

ORD2 is a programming language that offers full support of Python, plus additional ORD syntax (*Python-superset*)to improve textual IC design in the ORDeC project. It currently focuses on simplifiying the schematic entry phase, while also supporting the usual Python syntax for simulations or layouts. The language revision described in this file is called **ORD2**, it is a reworked version of the former **ORD1** which had it's own grammar and was not based on the Python language. Execution of ORD code results in a one-pass compiler step which transforms the input into context-based Python code. 
This is only made possible by leveraging the power of the :class:`OrdContext` which is explained in a later paragraph. The actual ORD grammar is written in Lark. Lark is a well-known and efficient Python parsing framework for grammars in EBNF form. The function call :func:`ord2_to_py` summarizes the necessary function calls, for a proper ORD to Python conversion. The conversion is mostly depedent on the :class:`Ord2Transformer` that inherits from :class:`PythonTransformer`. The **PythonTransformer** is capable of transforming any Python code written in ORD back to Python and the **Ord2Transformer** handles the conversion of the ORD syntax. The following paragraphs will summarize the logic behind the ORD to Python conversion. 


For a practical demonstration please visit the ORD tutorial :ref:`ord_tutorial` page!


ORD2 to Python in detail
------------------------

ORD is not a general-purpose programming language. It is developed to simplify certain steps in IC design, especially for the ORDeC project. The entire backend of ORDeC is already written in Python, but using Python for tasks like schematic entry can become complicated and cumbersome quite easily. ORD represents a more convenient syntax layer that makes structuring and describing IC designs much easier.

Mastering the ORD language requires understanding two crucial parts. First, the ORD language itself what it offers and what it represents. Second, the converted code. Understanding how ORD code is actually converted back to Python helps especially if you run into trouble while programming or designing, and it also helps you understand how the project works under the hood. Especially for complex programs and debugging purposes, understanding the Python side can become important.

ORD2 Contexts
-------------

The dotted syntax of ORD, which accesses the parent element, requires having a reference to the parent element. This structure therefore necessitates that statements and expressions inside a context block have a reference to the parent even after transformation of ORD back to Python. This logic is implemented with the so-called :class:`OrdContext`. It uses the Python with environment together with a context variable :class:`ContextVar` to always maintain a reference without requiring information about the parent during transformation. With ORD, we try to keep the transformation logic as minimal as possible and leverage the power of Python to supply the necessary constructs during execution.

.. code-block:: python

	# Type 1
	port xyz:
		.pos=(1,2)
	# Type 2
	port xyz(.pos=(1,2)


The following summary shows the must important functions and classes of ORD2 please, refer to the Python codebase for more background information and details


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
	:members:
	:undoc-members: