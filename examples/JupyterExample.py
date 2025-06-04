# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.16.7
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# # ORDeC Jupyter Example
#
# This file shows how Jupyter can be used to show data from the ORDeC library.
#
# It currently seems necessary to restart the Python kernel when ORDeC or its design library changes. (IPython's autoreload extension did not do the trick.) Therefore, I recommend defining a custom keyboard shortcut in Jupyter for the action *"restart the kernel, then re-run the whole notebook (no confirmation dialog)"*.

# Allow more than one result per cell:
from IPython.core.interactiveshell import InteractiveShell
InteractiveShell.ast_node_interactivity = "all"

# +
from ordec import lib

lib.Ringosc().schematic
lib.Inv().schematic
