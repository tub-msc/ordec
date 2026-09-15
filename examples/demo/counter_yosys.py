# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from notcl import TclTool
from pathlib import Path
import tempfile
import os
from nortl import Engine, Const, IfThenElse
from ordec.extlibrary import ExtLibrary
from ordec.core import *

class Yosys(TclTool):
    def cmdline(self):
        return ["yosys", "-c", self.script_name()]

def counter_rtl() -> str:
    """
    Describe an 8 bit up/down counter with enable using noRTL. Returns the
    generated SystemVerilog module 'counter_core', whose clock and reset ports
    (CLK_I and active-high RST_ASYNC_I) are fixed by noRTL.
    """
    engine = Engine("counter_core")
    down = engine.define_input("DOWN", 1)
    en = engine.define_input("EN", 1)
    val = engine.define_output("VAL", 8, 0)

    with engine.collapse_sync():
        # Leave the reset state: it re-applies reset values on every entry,
        # so the endless loop below must not return to it.
        engine.sync()
        with engine.while_loop(Const(True)):
            engine.set(val, IfThenElse(en == 1,
                IfThenElse(down == 1, val - 1, val + 1), val))
    # Collapse the empty wait states of sync() and while_loop() so that the
    # counter updates on every clock cycle.
    engine.empty_state_removal()
    return engine.to_verilog(include_modules=False)

# Structural wrapper around the noRTL-generated module: keeps the pin names
# expected by top.ord and adapts noRTL's reset to the active-low rst_ni.
counter_wrapper = """
module counter(
    input  wire clk_i,
    input  wire rst_ni,
    input  wire down_i,
    input  wire en_i,
    output wire [7:0] val_o
);
    counter_core core (
        .CLK_I(clk_i),
        .RST_ASYNC_I(~rst_ni),
        .DOWN(down_i),
        .EN(en_i),
        .VAL(val_o)
    );
endmodule
"""

def synthesize(verilog: str, top: str, lib: Path) -> str:
    """
    Synthesize the given top module in the SystemVerilog source string using
    the specified liberty (lib) file. Returns resulting Verilog netlist as
    string.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / 'in.sv'
        src.write_text(verilog)
        with Yosys() as yosys:
            yosys('yosys -import')
            yosys.read_verilog(src, sv=True)
            yosys.synth(top=top)
            yosys.flatten()
            yosys.opt()
            yosys.dfflibmap(liberty=lib)
            yosys.abc(liberty=lib)
            yosys.splitnets()
            yosys("yosys rename -hide */w:*\\[*")
            yosys.opt_clean(purge=True)
            yosys.write_verilog(Path(tmpdir) / 'out.v')
        return (Path(tmpdir) / 'out.v').read_text()

# Standard cell library setup:
stdcell_root = Path(os.getenv('ORDEC_PDK_IHP_SG13G2')) / 'libs.ref/sg13g2_stdcell'
stdcell_liberty = stdcell_root / 'lib/sg13g2_stdcell_typ_1p20V_25C.lib'
stdcell_lef = stdcell_root / 'lef/sg13g2_stdcell.lef'

extlib = ExtLibrary()
extlib.read_lef(stdcell_lef)
verilog = synthesize(counter_rtl() + counter_wrapper, 'counter', stdcell_liberty)
extlib.read_verilog(verilog)

@viewgen_noctx
def report_digital_design() -> Report:
    schematic = extlib['counter'].schematic
    stdcell_count = 0
    instances_of = {}
    for inst in schematic.all(SchemInstance):
        ref_name = inst.symbol.cell.name
        instances_of[ref_name] = instances_of.get(ref_name, 0) + 1
        stdcell_count += 1
    stdcell_table = []
    for ref_name, count in instances_of.items():
        stdcell_table.append(f"| {count} | {ref_name} |")
    report = Report()
    report.markdown("# Digital design report: 8 bit counter")
    report.svg(extlib['counter'].symbol)
    report.markdown(
        "## Standard cell count (schematic)\n"
        f"There are **{stdcell_count}** standard cells in the example design.\n"
        "\n"
        " | Cell count | Reference |\n"
        "| -- | -- |\n"
        + '\n'.join(stdcell_table)
    )
    return report
