# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.18.1
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# + tags=["remove-cell"]
# %xmode Plain
# -

# (ord_tutorial)=
#
# # ORD Tutorial
#
# ORD (Open Rapid Design) is ORDeC's hardware description language for IC design. 
# It is designed to make custom IC design more software-like and text-based, 
# as an alternative to traditional GUI-based tools.
# Follow this link for the full ORD language reference: {doc}`ord2`.
# Since version ORD1 is no longer maintained this tutorial focusses on ORD2. 
# The inverter will be used as an example circuit in this tutorial.


# + tags=["remove-input"]
from ordec.core import * 
from ordec.schematic import helpers
from ordec.ord2.context import ctx, OrdContext
from IPython.core.magic import Magics, magics_class, line_cell_magic
from IPython.display import Code

@magics_class
class OrdMagics(Magics):
    @line_cell_magic
    def ord(self, line, cell=None):
        """Custom magic for ORD language in Jupyter cells."""
        code = cell if cell else line
        from ordec.ord2.parser import ord2_to_py
        code = compile(ord2_to_py(code), "<string>", "exec")
        exec(code, self.shell.user_ns)

ip = get_ipython()
if ip is not None:
    ip.register_magics(OrdMagics)
# -

# ## 1. Cell definition
#
# A `cell` is the root of a ORD file, it acts as the base of the design you
# want to create. The name of the cell should describe the inner behaviour of the design {doc}`cell_and_generate`.

# + 
%%ord
cell Inv:
    pass
# -


# ## 2. Viewgen
# 
# Cell specific functions described by the ORDB format are always defined using the `viewgen` keyword. 
# They can be simulation views, schematics, symbols or layouts. Currently **schematics** and **symbols** are fully
# implemented in the ORD language! 

# + 
%%ord 
cell Inv:
    viewgen symbol:
    	pass
# -

# The view can be displayed with a simple function call. In the case of a symbol the resulting
# symbol gets displayed. But you don't need to worry about how you execute the ORD code yourself.
# Just use ORDeC's built-in web-interface! You can select the different views in the drop-down menu.

Inv().symbol 


# ## 3. Symbol
#
# The symbol represents the **outer connections** of the cell when importing it into another top level
# module. The keywords `inout`,`input` and `output` can be used to set the direciton of the Ports.
# The alignment describes the orientation of the symbol. 

# + 
%%ord
cell Inv:
    viewgen symbol:
        inout vdd(.align=Orientation.North)
        inout vss(.align=Orientation.South)
        input a(.align=Orientation.West)
        output y(.align=Orientation.East)
# -
# + tags=["remove-input"]
Inv().symbol
# -

# ## 4. Schematic
# 
# The schematic represents the **inner behaviour** of the cell and how the ports of the symbol are wired. 
# It supports multiple kinds of components which are explained in the following paragraphs.

# + 
%%ord
from ordec.lib.generic_mos import Nmos, Pmos

cell Inv:
    viewgen symbol:
        inout vdd(.align=Orientation.North)
        inout vss(.align=Orientation.South)
        input a(.align=Orientation.West)
        output y(.align=Orientation.East)

    viewgen schematic:
        port vdd(.pos=(2,13); .align=Orientation.North)
        port vss(.pos=(2,1); .align=Orientation.South)
        port y (.pos=(9,7); .align=Orientation.West)
        port a (.pos=(1,7); .align=Orientation.East)

        Nmos pd:
            .s -- vss
            .b -- vss
            .d -- y
            .pos = (3,2)
        Pmos pu:
            .s -- vdd
            .b -- vdd
            .d -- y
            .pos = (3,8)

        for instance in pu, pd:
            instance.g -- a
# -
# +
Inv().schematic
# -

# ### 4.1 Relative access (Dotted notation)
#
# You might have already recognized a specific feature of the ORD language which we call **relative access**
# or also **dotted notation**. Whenever an ORD specific element is defined a **context** gets opened.
# This context can be defined with the braces like `port vdd()` or with the colon plus an indent `Nmos pd:`.
# Those definitions are identical in the ORD language.
# Everything below inside this context can reference the parent object by using a leading `.`. The contexts 
# are hierarcically structured so even mulitiple leading dots are possible to access parent contexts.
#
# ```python
# # Type 1
# port vdd(.pos=(2,13); .align=Orientation.North)
# # Type 2
# port vdd:
#     .pos=(2,13) 
#     .align=Orientation.North
# ```
# Attributes must not be set directly on definition, they can also be set later in the code
# ```python
# port vdd(.align=Orientation.North)
# vdd.pos=(2,13)
# ```

# ### 4.2 Ports
#
# Ports defined in the symbol must be placed in the schematic aswell. This is done using the `port` keyword,
# the name of the port `vdd` and the attributes position and align.


# ### 4.3 Subcells
#
# Subcells are the key components in the design of the schematic, they must be imported from the file
# system using a normal Python-style import `from ordec.lib.generic_mos import Nmos, Pmos`. Those imported
# cells can be ORD or Python based cells. 

# ### 4.4 Connections
#
# Connections between elements are another unique feature of the ORD language. 
# They use the `--` symbol and should always be connected from an instance to a port or to a net.

# ### 4.5 Nets
#
# In the case of the inverter every port is only instance inside the schematic is connected to a port.
# But other designs might require connections between subcells or also branches. This logic can be implemented
# by internal `nets`. The **Nand** is an example circuit where a net is needed to connected the two Nmos transistors.

# + 
%%ord
cell Nand:
    viewgen symbol:
        output y(.align=Orientation.East)
        input a(.align=Orientation.West)
        input b(.align=Orientation.West)
        inout vdd(.align=Orientation.North)
        inout vss(.align=Orientation.South)

    viewgen schematic:
        port y(.align=Orientation.West; .pos=(25,6))
        port a(.align=Orientation.East; .pos=(1,4))
        port b(.align=Orientation.East; .pos=(1,17))
        port vdd(.align=Orientation.East; .pos=(1,23))
        port vss(.align=Orientation.East; .pos=(1,1))

        net net_conn

        Nmos n1(.pos=(10,2); .d -- net_conn; .s -- vss; .b -- vss; .g -- a)
        Nmos n2(.pos=(10,10); .d -- y; .s -- net_conn; .b -- vss; .g -- b)
        Pmos p1(.pos=(5,18); .d -- y; .s -- vdd; .b -- vdd; .g -- a)
        Pmos p2(.pos=(15,18); .d -- y; .s -- vdd; .b -- vdd; .g -- b)
# -
# + tags=["remove-input"]
Nand().schematic
# -

# ### 4.6 Paths
#
# ORDeC uses hierarchical subgraphs to add elements to a schematic. 
# When defining elements in the schematic they become children of the schematic subgraph. 
# Further nesting of elements can be achieved using *paths*. Those open a new subgraph 
# layer and elements can be added by using indices. 
# This enables definition of **list** like elements which are especially powerful in 
# combination with the parametrization feature of ORDeC.

# ```python
# path bit
# path bit[i]
# ```


# ### 4.7 Cell parameters
#
# Cells can be parametrized to make them reusable and adjust to new applications.
# This enables customizable cells like in this case a register with variable amount of bits.

# + 
%%ord
cell MultibitReg_ArrayOfStructs:
    bits = Parameter(int)
    viewgen symbol:
        input vdd(.align=Orientation.North)
        input vss(.align=Orientation.South)
        path bit
        for i in range(self.bits):
            path bit[i]
            input bit[i].d(.align=Orientation.West)
            output bit[i].q(.align=Orientation.East)
        input clk(.align=Orientation.West)
# -

# Parameters for subcells are set using the dollar `$` operator.
# In this case we set the length `l` to 100n and the width `w` to 200n.
# ORD supports all common SI suffixes for cell parameters
# (a=atto, f=femto, n=nano, u=micro, m=milli, k=kilo, M=Mega, G=Giga, T=Terra)

# +
%%ord
cell Inv:
    viewgen symbol:
        inout vdd(.align=Orientation.North)
        inout vss(.align=Orientation.South)
        input a(.align=Orientation.West)
        output y(.align=Orientation.East)

    viewgen schematic:
        port vdd(.pos=(2,13); .align=Orientation.North)
        port vss(.pos=(2,1); .align=Orientation.South)
        port y (.pos=(9,7); .align=Orientation.West)
        port a (.pos=(1,7); .align=Orientation.East)

        Nmos pd:
            .s -- vss
            .b -- vss
            .d -- y
            .pos = (3,2)
            .$l = 100n
            .$w = 200n
        Pmos pu:
            .s -- vdd
            .b -- vdd
            .d -- y
            .pos = (3,8)
            .$l = 100n
            .$w = 200n

        for instance in pu, pd:
            instance.g -- a
# -
# + tags=["remove-input"]
Inv().schematic
# -

# ## 5. Python support
#
# ORD is not a standalone language. It is a language extension (superset) of Python!
# ORD is capable to run and include any Python code which has the advantage that Python functionalities
# can be used directly inside ORD. Furthermore, ORDeC features which are not yet
# implemented in ORD itself, can just be written as Python components inside an ORD file :)

# +
%%ord
def add(x, y):
	return x + y

cell Inv:
    viewgen symbol:
        inout vdd(.align=Orientation.North)
        inout vss(.align=Orientation.South)
        input a(.align=Orientation.West)
        output y(.align=Orientation.East)
        print(f"Result: {add(1, 2)}")

# + tags=["remove-input"]
Inv().symbol
# -

# ## 6. Import ORD files
#
# Every module written in ORD can be imported like a normal Python file through the ORD importer!

import ordec.importer
import ordec.lib.ord2_test.inverter

# ## 7. ORD version
#
# A header in the ORD file is used to decide which ORD language version the code is written in.
# The header should be placed in line one. The default version is currently version one if the version header is not present.

# +
# -*- version: ord2 -*-
# -
