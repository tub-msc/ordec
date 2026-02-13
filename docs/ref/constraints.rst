:mod:`ordec.core.constraints` --- Linear constraint solving
===========================================================

.. automodule:: ordec.core.constraints

This module allows generating attributes values from a set of user-defined
linear constraints (equalities and inequalities) instead of manually computing
attribute values. It is used the following way:

1) Create a :class:`Solver` instance for the subgraph.
2) Add constaints via the constrain() method.
3) Call the solve() method to solve the constriants and fill in the
   attributes.

Only :class:`ConstrainableAttr` attributes can be constrained.

**Example:**

.. code-block:: python

    l = Layout(ref_layers=layers) 
    l.r1 = LayoutRect(layer=layers.Metal1)
    l.r2 = LayoutRect(layer=layers.Metal1)

    s = Solver(l)
    s.constrain(l.r1.rect.height >= 500)
    s.constrain(l.r1.rect.width >= 150)
    s.constrain(l.r1.rect.southwest == (100, -100)
    s.constrain(l.r2.rect.lx >= l.r1.rect.ux + 150)
    s.constrain(l.r2.rect.width == -l.r1.rect.height + 800)
    s.constrain(l.r2.rect.width <= 150)
    s.constrain(l.r2.rect.height == 150)
    s.constrain(l.r2.rect.cy == l.r1.rect.cy)
    s.solve()


.. autoclass:: Solver
  :members:

Linear terms
------------

.. autoclass:: Variable
  :members:

.. autoclass:: LinearTerm
  :members:

.. autoclass:: Vec2LinearTerm
  :show-inheritance:
  :members:

.. autoclass:: Rect4LinearTerm
  :show-inheritance:
  :members:

.. autoclass:: TD4LinearTerm
  :show-inheritance:
  :members:

Constraints
-----------

.. autoclass:: Constraint
  :members:

.. autoclass:: MultiConstraint
  :members:

.. autoclass:: LessThanOrEqualsZero
  :show-inheritance:
  :members:

.. autoclass:: EqualsZero
  :show-inheritance:
  :members:


Under the hood
--------------

.. autoclass:: ConstrainableAttr
  :members:

.. autoclass:: ConstrainableAttrPlaceholder
  :members:
