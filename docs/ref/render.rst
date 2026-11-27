:mod:`ordec.render` --- Rendering views to SVG and PNG
======================================================

.. automodule:: ordec.render
   :members: render_svg, render_png

Example (``import ordec.importer`` makes ``.ord`` modules importable)::

    import ordec.importer
    from ordec.render import render_png
    from ordec.examples.adder_pnr import RippleAdder

    render_png(RippleAdder().layout, 'adder.png')
    render_png(RippleAdder().schematic, 'adder_sch.png', size=800)

Layouts
-------

.. automodule:: ordec.layout.svg
   :members: layout_svg
