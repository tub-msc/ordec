IPython integration
-------------------

*IPython.display.SVG* leads to problems, in my case with font rendering. This is a known problem (see `IPython issue #1866`_ and `IPython issue #700`_). The underlying problem is that the provided data is directly embedded into Jupyter's DOM. One solution seems to be to mess around with the XML (proposed in `IPython issue #700`_).

The working solution is to use a *\<img\>* tag and embed the SVG as Base64 data url. This is now done by through the **\_repr_html\_** method of selected View classes.

An earlier, more explicit approach was to write::

  IPython.display.Image(url=svg2url(render_schematic(lib.Inverter().schematic)))

.. _`IPython issue #700`: https://github.com/ipython/ipython/issues/700
.. _`IPython issue #1866`: https://github.com/ipython/ipython/issues/1866/