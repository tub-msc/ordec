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
# ORD (Open Rapid Design) is ORDeC's **hardware description language for IC design**. 
# It is designed to make custom IC design more software-like and text-based, 
# as an alternative to traditional GUI-based tools.
# Follow this link for the full ORD language reference: {doc}`ord2`.

# This tutorial provides a starting point for writing basic ORD code.  
# It covers all the main structures and features that ORD currently offers 
# and will be extended in the future as ORD gains more features. The inverter 
# will be the most referenced design throughout the tutorial, since it is 
# well-known and easy to get started with. Since ORD1 is no longer maintained, 
# all examples are written in ORD2. 

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

# ## 1. Cell
#
# A `cell` is the **root** of an ORD file. It acts as the base of the design you
# want to create. The name of the cell should describe the inner behavior of the design {doc}`cell_and_generate`.

# + 
%%ord
cell Inv:
    pass
# -


# ## 2. Viewgen
# 
# Cell-specific generator functions described by the ORDeC data schema are defined using the `viewgen` keyword. 
# They can be simulation, schematic, symbol, or layout views. Currently, **schematic** and **symbol** views are fully
# implemented in the ORD language! 

# + 
%%ord 
cell Inv:
    viewgen symbol:
    	pass
# -

# The view can be displayed with a simple function call. For a symbol, the resulting
# symbol gets displayed. However, you don't need to worry about how to execute the ORD code yourself.
# Just use ORDeC's built-in web interface {doc}`../webui`!

Inv().symbol 


# ## 3. Symbol
#
# The symbol represents the **outer connections** of the cell when importing it into another top level
# module. The keywords `inout`, `input` and `output` are used to set the direction of the Ports.
# The alignment describes the orientation of the port in the symbol. 

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
# The schematic represents the **inner behavior** of the cell and how the ports of the symbol are wired. 
# It supports multiple kinds of components that are explained in the following paragraphs.

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

# ### 4.1 Relative access
#
# You might have already recognized a specific feature of the ORD language called **relative access**
# or **dotted notation**. Whenever an ORD-specific element is defined, a **context** is opened.
# This context can be defined with the braces like `port vdd()` or with the Python-style block based notation `Nmos pd:`.
# Both definitions are identical in the ORD language.
# Every statement or expression inside this context can reference the parent object by using a leading `.`. The contexts 
# are hierarchically structured, so even multiple leading dots are possible to access parent contexts.
#
# ```python
# # Type 1
# port vdd(.pos=(2,13); .align=Orientation.North)
# # Type 2
# port vdd:
#     .pos=(2,13) 
#     .align=Orientation.North
# ```
# Attributes must not be set directly on definition, they can also be set at a later point in the code
# ```python
# port vdd(.align=Orientation.North)
# vdd.pos=(2,13)
# ```

# ### 4.2 Ports
#
# Ports defined in the symbol must be placed in the schematic as well. This is done using the `port` keyword,
# the name of the port `vdd`, and the attributes position and alignment.

# ### 4.3 Subcells
#
# Subcells are the key components in the design of the schematic, they must be imported from the file
# system using a normal Python-style import `from ordec.lib.generic_mos import Nmos, Pmos`. The imported
# cells can be ORD- or Python-based. Referencing cells without the import is also possible, if the 
# other cell is defined in the same source file. 

# ### 4.4 Connections
#
# Connections between elements are another unique feature of the ORD language. 
# They use the `--` operator and should always be connected from an instance to a `port` or `net`.

# ### 4.5 Nets
#
# In the case of the inverter, every instance inside the schematic is connected directly to a port.
# However, other designs might require connections between subcells or branches. This logic can be implemented
# using internal `nets`. The **Nand** is an example circuit where a net is needed to connect the two Nmos transistors.

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
# When defining elements in the schematic, they become children of the schematic subgraph. 
# Further nesting of elements can be achieved using `paths`. Paths open a new subgraph 
# layer where elements can be added using indices. 
# This enables definition of **list-like** elements, which are especially powerful in 
# combination with the parametrization feature of ORDeC.

# ```python
# path bit
# path bit[i]
# ```

# ### 4.7 Parametrization
#
# **Cells can be parametrized** to make them reusable and adjust to new applications.
# This enables customizable cells like, in this case, a register with a variable number of bits.

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

# **Parameters for subcells** are set using the dollar `$` operator.
# In this example, we set the length of the transistors `l` to 100n and the width `w` to 200n.
# ORD supports all common SI suffixes for cell parameters that use the `Rational` class type {doc}`rational`.
# (a=atto, f=femto, n=nano, u=micro, m=milli, k=kilo, M=Mega, G=Giga, T=Tera)

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
# ORD is not a standalone language. It is a **language extension (superset) of Python**!
# ORD is capable of running and including any Python code, which has the advantage that Python functionalities
# can be used directly inside ORD. Furthermore, ORDeC features that are not yet
# implemented in ORD itself can be written as Python components inside an ORD file :)
# But it is not a problem if you are not used to Python. ORD as described here doesn't
# require understanding complex Python language features, but some knowledge definitely helps
# getting started!

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

# ## 6. Import ORD
#
# Every module written in ORD can be **imported like a Python module** through the ORD importer!

# +
# Get the ORDeC importer
import ordec.importer
# Import your ORD file!
from ordec.lib.ord2_test.inverter import Inv
# -

# ## 7. ORD version
#
# A header in the ORD file is used to decide which ORD language version the code is written in.
# The header should be placed in the **first line**. The **default** version is currently **version one** if the version header is not present.

# +
# -*- version: ord2 -*-
# -

# I hope this short tutorial gave you some insights into how to get started
# writing ORD code! Feel free to check out the ORD examples `ordec.lib.ord2_test` 
# by importing and adjusting them in the web interface. 
# 
# **Happy ORD coding!**