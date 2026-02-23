#!/usr/bin/env python3
from notcl import TclTool
from pathlib import Path
import tempfile
import json
import os
from typing import Iterable
from ordec.extlibrary import ExtLibrary
from ordec.core import *
from ordec.report import *

class Yosys(TclTool):
    def cmdline(self):
        return ["yosys", "-c", self.script_name()]


def synthesize(source_files: Iterable[Path], top: str, lib: Path, enable_slang: bool=False) -> str:
    """
    Returns Verilog netlist as string.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with Yosys() as yosys:
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

def read_verilog(verilog_str):
    """
    Returns unpacked JSON from Yosys.
    """

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / 'in.v').write_text(verilog_str)
        with Yosys() as yosys:
            yosys('yosys -import')
            yosys.read_verilog(Path(tmpdir) / 'in.v')
            yosys.write_json(Path(tmpdir) / 'out.json')
        return json.loads((Path(tmpdir) / 'out.json').read_text())

stdcell_root = Path(os.getenv('ORDEC_PDK_IHP_SG13G2')) / 'libs.ref/sg13g2_stdcell'
liberty = stdcell_root / 'lib/sg13g2_stdcell_typ_1p20V_25C.lib'
lef = stdcell_root / 'lef/sg13g2_stdcell.lef'

extlib = ExtLibrary()
extlib.read_lef(lef)
verilog = synthesize([Path(__file__).parent/'counter.v'], 'counter', liberty)
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
        #Svg(Vco().symbol),
        Markdown(
            "## Standard cell count (schematic)\n"
            f"There are **{stdcell_count}** standard cells in the example design.\n"
            "\n"
            " | Cell count | Reference |\n"
            "| -- | -- |\n"
            + '\n'.join(stdcell_table)
        )
    ])

if __name__ == "__main__":
    # For timing
    extlib['counter'].symbol
    extlib['counter'].schematic
