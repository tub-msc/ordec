:mod:`ordec.core.geoprim` --- Geometric primitives
==================================================

.. automodule:: ordec.core.geoprim

2D vectors
----------

.. autoclass:: Vec2Generic
  :exclude-members: __init__, __new__
  :members:

.. autoclass:: Vec2R
  :exclude-members: __init__, __new__
  :members:

.. autoclass:: Vec2I
  :exclude-members: __init__, __new__
  :members:

Rectangle types
---------------

.. autoclass:: Rect4Generic
  :exclude-members: __init__, __new__
  :members:

.. autoclass:: Rect4R
  :exclude-members: __init__, __new__, vector_cls
  :members:

.. autoclass:: Rect4I
  :exclude-members: __init__, __new__, vector_cls
  :members:


2D Translation, X/Y mirroring and 90° rotation
----------------------------------------------

.. autoclass:: TD4
  :exclude-members: __init__, __new__
  :members:

.. autoclass:: D4
  :members:

  .. figure:: geoprim_D4.svg

    Elements of the dihedral group D4 applied to a half arrow.

.. autoclass:: Orientation
  :members:
