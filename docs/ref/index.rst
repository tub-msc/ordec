User Reference
==============

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   datamodel_demo

.. _data-schema:

.. figure:: architecture.svg
   :scale: 120 %
   :alt: ORDeC architecture block diagram

   Overview of ORDeC's architecture


Data schema
-----------

The **common schema for IC design data** ensures that different modules of ORDeC speak the same language and can interact seamlessly.

.. automodule:: ordec.schema
   :member-order: bysource
   :members: 
   :undoc-members:
   :exclude-members: check_integrity

Data model
----------

.. currentmodule:: ordec

.. autoclass:: Cell
   :members:
   :exclude-members: __init__

.. autoclass:: Node
   :members:
   :exclude-members: Children, __init__

.. autoclass:: View
   :members:

Geometric primitives
--------------------

.. autoclass:: Vec2R
    :exclude-members: __init__, __new__

.. autoclass:: Rect4R
    :exclude-members: __init__, __new__

.. autoclass:: TD4
    :exclude-members: __init__, __new__

.. autoclass:: D4
    :members:

.. autoclass:: Orientation

Rational numbers
----------------

ORDeC represents coordinates of schematics internally as :class:`ordec.Rational`. So far, it seems like this was a good idea, as it prevents the mess of floating-point number comparisons. For example, we can use them as (hashable) dictionary keys to find connectivity in sanitize_schematic. Also, the limitations and problems of having to define library units are absent.

It is not clear yet whether this approach will also be used for layout data.

.. autoclass:: Rational
    :exclude-members: __init__, __new__
