# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.16.4
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# # Development playground: new SVG renderer (render2)
#
# Todos:
#
# - add g around instances (using container function arg)
# - adapt tests, rename render2 to render, glue code changes, remove old cairo render.py
# - new tests should only compare svg xml. the long float numbers could cause problems here, can we somehow ensure that the strings are the same on platforms with different FP hardware?
# - understand how to properly compute the scaling factor for text instead of just guessing a value (0.05).
# - stick with the condensed font hack for now.
# - in the medium term, make the symbols more compact overall and put params outside symbol.
# - can we deliver the font to the browser so that the user does not need to have inconsolate installed and the svg does not need to embed the font (some sort of browser font inheritance from the html page to the svg context)?
# - firefox and cairosvg render fonts slightly differently (baseline). figure out whether an alternative dominant-baseline setting could fix this.

# Allow more than one result per cell:
from IPython.core.interactiveshell import InteractiveShell
InteractiveShell.ast_node_interactivity = "all"

# +
from ordec import R, render2, lib
from ordec.lib import test as lib_test
from IPython.display import display, SVG, Image

s = render2.SVG()
s.render_symbol(lib.And2().symbol)
display(SVG(s.svg()))

s = render2.SVG()
s.render_schematic(lib_test.RotateTest().schematic)
#s.render_schematic(lib_test.TestNmosInv(variant='no_wiring', add_conn_points=False, add_terminal_taps=True).schematic)
display(SVG(s.svg()))

#display(Image(s.png(), format='png'))

# Use this pretty() function intead of adding indentation to the XML itself.
# Addinng indentation / spaces / newlines in the XML would mess up the text rendering a bit,
# as some spaces would get rendered to the output graphic.
def pretty(xml):
    import lxml.etree as etree
    return etree.tostring(etree.fromstring(xml), pretty_print=True).decode('ascii')
#print(pretty(s.svg()))

