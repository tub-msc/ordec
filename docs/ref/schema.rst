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

Pins are drawn as an arrow indicating the pin type plus the pin name. Symbols
whose drawing makes this obvious (e.g. the terminals of a resistor) can hide
either one per pin with ``Pin.show_arrow`` and ``Pin.show_label``. Hidden pin
names remain part of the rendered SVG (class ``detail``, like the grid) and
show up in the detail view of the web UI. Labels of vertical (North/South)
pin stubs run along the stub; symbols with short pin names can draw them
horizontally instead with ``Pin.rotate_label = False``.

Besides pins and drawn geometry, a symbol carries :class:`SymbolAnnotation`
lines (instance name, cell name, parameters). Each line has a unique
``key``: an :class:`AnnotationKind` for the instance and cell name, else the
parameter name, drawn as ``key=value``. Lines referencing a
:class:`SymbolAnnotationStack` are drawn at its fixed position, typically
inside the symbol outline. The other lines form the annotation block, which
is placed as a whole beside the symbol. Schematics place the blocks after
wiring (:func:`ordec.schematic.place_annotations`, stored in
``SchemInstance.annotation_pos``): each block goes to the first side of the
symbol with an empty spot, in the order east, north, west, south, and there
to the empty spot nearest to the symbol's center, where empty means no
overlap with wires, ports, tap points, drawn symbol geometry, pin labels or
other blocks. Blocks of box symbols (``Symbol.is_box``) try the north side
first, aiming at the spot above the top left corner, like the reference
designators of ICs in common schematic conventions. Keeping away from other
instances, so that it stays clear where a block belongs, takes precedence
over the side. Mirrored instances swap east and west (or north and south),
so that e.g. mirrored transistors keep their blocks on the outer side;
rotations by 90 degrees keep the order. By default, every annotation line is
a text row of its own. Where a flatter block gets closer to the symbol,
consecutive lines share a row (``SchemInstance.annotation_wrap``). The text
stays horizontal; blocks left of their symbol are right-aligned. A schematic
may set ``SchemInstance.annotation_pos`` explicitly; lines that need a fixed
position within the symbol belong in a :class:`SymbolAnnotationStack`. Each
annotation line has a ``shown`` flag, which a schematic can override per
instance with :class:`SchemAnnotationOverride` to declutter the drawing.

Symbols start out with the default annotations (see
:class:`Symbol`, which hides parameters left at their
default unless they are declared with ``Parameter(..., hide_default=False)``)
and may modify, remove or extend them. :meth:`Symbol.place_pins` makes a box
symbol: it arranges the pins on the sides of the outline (independently of
any text) and draws the outline. The cell name goes into the middle of the
box if it fits between the pin labels; the instance name, the parameters
and a cell name that does not fit form the annotation block beside the box.
Symbol viewgens that set no outline get this automatically.

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

.. autoclass:: AnnotationKind
   :members:
   :undoc-members:

.. autoclass:: SymbolAnnotationStack
   :members:
   :undoc-members:

.. autoclass:: HAlign
   :members:
   :undoc-members:

.. autoclass:: VAlign
   :members:
   :undoc-members:

.. autoclass:: SymbolAnnotation
   :members:
   :undoc-members:

Schematics
----------

The ``orient`` of pins, ports and tap points is a direction; mirroring has
no visible effect on them, so it is stored unflipped. :class:`Pin` and
:class:`SchemPort` point towards their wire: a pin points out of its symbol
to where the wire attaches, and a port is the inside view of that pin, so an
input pin facing ``West`` corresponds to a port facing ``East``, with its
label left of the wire. :class:`SchemTapPoint` instead points away from its
wire, in the direction its glyph and label extend: a supply tap with
``orient=North`` draws its arrow upwards, a ground tap with ``orient=South``
downwards. A tap at an instance pin therefore has the orient of that pin.

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

.. autoclass:: SchemAnnotationOverride
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

Unresolved instances during construction
----------------------------------------

During view construction, an instance created from a Cell class
(``MyCell x:`` in ORD) may not have its ``symbol`` (:class:`SchemInstance`)
or ``ref`` (:class:`LayoutInstance`) resolved yet. The deferred state (cell,
parameters, unresolved pin connections) is managed by the view context, not
by schema nodes; it is resolved at the latest when the view context exits.

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
