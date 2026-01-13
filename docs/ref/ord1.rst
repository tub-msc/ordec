:mod:`ordec.ord1` --- ORD1 language
===================================

ORD1 is the initial version of the IC design language in the ORDeC project. It was used to evaluate a text-based entry language for IC design within the ORDeC platform. ORD1 uses a standalone grammar different from Python, which results in a complex transformation to the Python target language. ORD1 is no longer maintained because of several compiler problems, like scoping and liveness of variables, which would require a more complex semantic backend that interferes with our one-pass ORD-to-Python compiler approach. Nevertheless, this version gave us various insights into how we want to further integrate the ORD language in future versions. The examples in the project that use ORD1 are still working.

.. automodule:: ordec.ord1


Parser
------

.. autofunction:: load_ord_from_string
.. autofunction:: ord1_to_py

Lark Transformer
----------------

.. autoclass:: OrdecTransformer

AST Transformer
---------------

.. autoclass:: SchematicModifier
	:members:

Implicit Processing
-------------------

.. autofunction:: preprocess
.. autofunction:: postprocess

Optimize Position
-----------------

.. autofunction:: get_pos_with_constraints
