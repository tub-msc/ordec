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

# # Development playground: new SVG renderer ("render2")

# Allow more than one result per cell:
from IPython.core.interactiveshell import InteractiveShell
InteractiveShell.ast_node_interactivity = "all"

# +
from ordec import lib, render

print(render(lib.Inv().schematic, enable_grid=False).svg().decode('ascii'))
# -

# Implicit rendering in Jupyter via \_repr\_html\_():

# +
from ordec import lib, R
from ordec.lib import test as lib_test

lib.Inv().schematic
lib.Inv().symbol
lib_test.RotateTest().schematic
# -

# Explicit rendering via the render() function / Renderer class of order.render:

# +
from ordec import render
from IPython.display import display, SVG, Image

s = render(lib.And2().symbol)
display(SVG(s.svg()))

#s = render(lib_test.RotateTest().schematic)
s = render(lib_test.Inv().schematic)
#s = render(lib_test.TestNmosInv(variant='no_wiring', add_conn_points=False, add_terminal_taps=True).schematic)
display(SVG(s.svg()))

#display(Image(s.png(), format='png'))
