# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from notcl import TclTool
from pathlib import Path
import tempfile
import json
import os
from ordec.extlibrary import ExtLibrary
from ordec.core import *
from ordec.report import *

class Yosys(TclTool):
    def cmdline(self):
        return ["yosys", "-c", self.script_name()]

def synthesize(source_files: list[Path], top: str, lib: Path, enable_slang: bool=False) -> str:
    """
    Synthesize the given top module in the source files using the specified
    liberty (lib) file. Returns resulting Verilog netlist as string.

    The flag enable_slang enables SystemVerilog support using the
    `yosys-slang <https://github.com/povik/yosys-slang>`_ extension.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with Yosys() as yosys:
            if enable_slang:
                yosys("yosys plugin -i slang")
            yosys('yosys -import')

            if enable_slang:
                yosys.read_slang(*list(source_files), top=top)
            else:
                yosys.read_verilog(*list(source_files))
            yosys.synth(top=top)
            #yosys.hierarchy(top=top)
            #yosys('yosys proc')
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

# Input RTL design:
rtl_sources = [Path(__file__).parent/'counter.v']
rtl_top = 'counter'

extlib = ExtLibrary()
extlib.read_lef(stdcell_lef)
verilog = synthesize(rtl_sources, rtl_top, stdcell_liberty, enable_slang=True)
extlib.read_verilog(verilog)

@generate_func
def report_digital_design():
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
    return Report([
        Markdown("# Digital design report: 8 bit counter"),
        Svg.from_view(extlib['counter'].symbol),
        Markdown(
            "## Standard cell count (schematic)\n"
            f"There are **{stdcell_count}** standard cells in the example design.\n"
            "\n"
            " | Cell count | Reference |\n"
            "| -- | -- |\n"
            + '\n'.join(stdcell_table)
        )
    ])
