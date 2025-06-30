Rational numbers
================

ORDeC represents coordinates of schematics internally as :class:`ordec.Rational`. So far, it seems like this was a good idea, as it prevents the mess of floating-point number comparisons. For example, we can use them as (hashable) dictionary keys to find connectivity in sanitize_schematic. Also, the limitations and problems of having to define library units are absent.

It is not clear yet whether this approach will also be used for layout data.

.. currentmodule:: ordec

.. autoclass:: Rational
    :exclude-members: __init__, __new__
