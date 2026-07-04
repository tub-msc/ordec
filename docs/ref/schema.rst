:mod:`ordec.core.schema` --- Common schema for IC design data
=============================================================

This common schema ensures that different modules of ORDeC speak the same language and can interact seamlessly.

.. automodule:: ordec.core.schema

General stuff
-------------

.. autoclass:: SourceLocInfo
   :members:
   :undoc-members:

.. autoclass:: PolyVec2R
   :members:
   :undoc-members:

.. autoclass:: PolyVec2I
   :members:
   :undoc-members:

Symbols
-------

.. autoclass:: Symbol
   :members:
   :undoc-members:
   :exclude-members:

.. autoclass:: Pin
   :members:
   :undoc-members:

.. autoclass:: PinType
   :members:
   :undoc-members:

.. autoclass:: SymbolPoly
   :members:
   :undoc-members:

.. autoclass:: SymbolArc
   :members:
   :undoc-members:

Schematics
----------

.. autoclass:: Schematic
   :members:
   :undoc-members:

.. autoclass:: Net
   :members:
   :undoc-members:

.. autoclass:: SchemPort
   :members:
   :undoc-members:

.. autoclass:: SchemWire
   :members:
   :undoc-members:

.. autoclass:: SchemInstance
   :members:
   :undoc-members:

.. autoclass:: SchemInstanceConn
   :members:
   :undoc-members:

.. autoclass:: SchemTapPoint
   :members:
   :undoc-members:

.. autoclass:: SchemConnPoint
   :members:
   :undoc-members:

.. autoclass:: SchemErrorMarker
   :members:
   :undoc-members:

.. autoclass:: SchemErrorType
   :members:
   :undoc-members:

Unresolved schematic instances
------------------------------

During schematic construction, instances may reference a Symbol that is not
determined yet. These nodes hold the pending placement, connections and
parameters until the referenced Symbol is resolved into a :class:`SchemInstance`.

.. autoclass:: SchemInstanceUnresolved
   :members:
   :undoc-members:

.. autoclass:: SchemInstanceUnresolvedConn
   :members:
   :undoc-members:

.. autoclass:: SchemInstanceUnresolvedParameter
   :members:
   :undoc-members:

Simulation hierarchy
--------------------

.. autoclass:: SimHierarchy
   :members:
   :undoc-members:

.. autoclass:: SimInstance
   :members:
   :undoc-members:

.. autoclass:: SimNet
   :members:
   :undoc-members:

.. autoclass:: SimPin
   :members:
   :undoc-members:

.. autoclass:: SimParam
   :members:
   :undoc-members:

.. autoclass:: SimType
   :members:
   :undoc-members:

Technology definitions
----------------------

.. autoclass:: GdsLayer
   :members:
   :undoc-members:

.. autoclass:: RGBColor
   :members:
   :undoc-members:

.. autofunction:: rgb_color

.. autoclass:: LayerStack
   :members:
   :undoc-members:

.. autoclass:: Layer
   :members:
   :undoc-members:

Routing
-------

Routing specifications parametrize the :class:`~ordec.layout.SRouter`
independently of the :class:`LayerStack`, describing the per-layer widths, via
geometry and routing order used to connect nets.

.. autoclass:: RoutingSpec
   :members:
   :undoc-members:

.. autoclass:: RoutingSpecLayer
   :members:
   :undoc-members:

Layout
------

.. autoclass:: Layout
   :members:
   :undoc-members:

.. autoclass:: LayoutLabel
   :members:
   :undoc-members:

.. autoclass:: LayoutPoly
   :members:
   :undoc-members:

.. autoclass:: LayoutPath
   :members:
   :undoc-members:

.. autoclass:: LayoutRect
   :members:
   :undoc-members:

.. autoclass:: LayoutInstance
   :members:
   :undoc-members:

.. autoclass:: LayoutInstanceArray
   :members:
   :undoc-members:

.. autoclass:: LayoutPin
   :members:
   :undoc-members:

.. autoclass:: PathEndType
   :members:
   :undoc-members:

Reports and plots
-----------------

Reports are subgraphs of vertically stacked report elements, used to present
textual, tabular and graphical results (e.g. course lesson feedback or
simulation plots) in the web interface.

.. autoclass:: Report
   :members:
   :undoc-members:

.. autoclass:: ReportElement
   :members:
   :undoc-members:

.. autoclass:: Markdown
   :members:
   :undoc-members:

.. autoclass:: PreformattedText
   :members:
   :undoc-members:

.. autoclass:: Html
   :members:
   :undoc-members:

.. autoclass:: PassFail
   :members:
   :undoc-members:

.. autoclass:: Svg
   :members:
   :undoc-members:

.. autoclass:: PlotGroup
   :members:
   :undoc-members:

.. autoclass:: Plot2D
   :members:
   :undoc-members:

.. autoclass:: Plot2DSeries
   :members:
   :undoc-members:

.. autoclass:: ScaleType
   :members:
   :undoc-members:

Design rule checking (DRC)
--------------------------

A DRC report collects design rule violations found in a :class:`Layout`.
Violations are grouped into categories and attached to the cell they occur in;
each item carries one or more geometry nodes (boxes, edges, polygons, paths,
text or values) locating and describing the violation.

.. autoclass:: DrcReport
   :members:
   :undoc-members:

.. autoclass:: DrcCategory
   :members:
   :undoc-members:

.. autoclass:: DrcCell
   :members:
   :undoc-members:

.. autoclass:: DrcItem
   :members:
   :undoc-members:

.. autoclass:: DrcBox
   :members:
   :undoc-members:

.. autoclass:: DrcEdge
   :members:
   :undoc-members:

.. autoclass:: DrcEdgePair
   :members:
   :undoc-members:

.. autoclass:: DrcPoly
   :members:
   :undoc-members:

.. autoclass:: DrcPath
   :members:
   :undoc-members:

.. autoclass:: DrcText
   :members:
   :undoc-members:

.. autoclass:: DrcValue
   :members:
   :undoc-members:

Layout vs. schematic (LVS)
--------------------------

An LVS report captures the comparison of an extracted :class:`Layout` against
its :class:`Schematic`. Results are organized per circuit pair, with individual
items recording the match status of nets, devices, pins and subcircuits.

.. autoclass:: LvsReport
   :members:
   :undoc-members:

.. autoclass:: LvsCircuitPair
   :members:
   :undoc-members:

.. autoclass:: LvsItem
   :members:
   :undoc-members:

.. autoclass:: LvsStatus
   :members:
   :undoc-members:

.. autoclass:: LvsItemType
   :members:
   :undoc-members:
