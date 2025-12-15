:mod:`ordec.core.constraints` --- Linear constraint solving
===========================================================


.. automodule:: ordec.core.constraints

Solver interface
----------------

.. autoclass:: Solver

Linear terms
------------

.. autoclass:: LinearTerm

.. autoclass:: Vec2LinearTerm

.. autoclass:: Rect4LinearTerm

.. autoclass:: TD4LinearTerm

Constraints
-----------

.. autoclass:: Constraint

.. autoclass:: MultiConstraint

.. autoclass:: LessThanOrEqualsZero

.. autoclass:: EqualsZero


Under the hood
--------------

.. autoclass:: ConstrainableAttr

.. autoclass:: ConstrainableAttrPlaceholder

.. autoclass:: Variable
