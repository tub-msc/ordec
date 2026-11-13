# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import re
import shlex
import subprocess
from pathlib import Path

from ..core import *

logger = logging.getLogger(__name__)

#: Magic script for a full DRC of a GDS file, see the script for its variables.
DRC_SCRIPT = Path(__file__).with_name('magic_drc.tcl')


def run(script, cwd, rcfile, capture=None, env=None, **kwargs):
    """
    Run magic Tcl script 'script' in directory 'cwd' with the technology
    that the startup file 'rcfile' loads. The keyword args are set as Tcl
    variables before the script runs.

    Args:
        capture: Optional file name (relative to cwd) to which stdout and
            stderr are redirected.
        env: Optional environment variables in addition to the inherited
            ones, e.g. for the startup file to find the PDK.

    Raises:
        subprocess.CalledProcessError: if the script raises a Tcl error.
    """
    cmdline = ['magic', '-dnull', '-noconsole', '-rcfile', str(rcfile)]
    # Magic exits with 0 when a script given on its command line fails, so
    # the script is sourced from stdin, where a Tcl error exits with 1.
    commands = ['set %s {%s}' % (k, v) for k, v in kwargs.items()]
    commands += [
        'if {[catch {source {%s}}]} {puts stderr $::errorInfo; exit 1}' % script,
        'quit -noprompt',
    ]
    stdin = '\n'.join(commands) + '\n'
    env = os.environ | (env or {})
    logger.debug("%s %s", cwd, shlex.join(cmdline))
    if capture is None:
        subprocess.run(cmdline, cwd=cwd, input=stdin, text=True, env=env, check=True)
    else:
        with open(Path(cwd) / capture, 'w') as f:
            subprocess.run(cmdline, cwd=cwd, input=stdin, text=True, env=env, check=True,
                stdout=f, stderr=subprocess.STDOUT)



def parse_drc(filename, report: DrcReport, directory: Directory = None):
    """
    Parse the error list written by DRC_SCRIPT, appending the violations
    into the given DrcReport subgraph.

    Magic checks each cell flat together with its subcells, so the list
    repeats the violations of a subcell in every cell above it. As in
    KLayout's deep mode, each violation is attached once to the lowest cell
    holding it, in that cell's coordinates: an error box of a cell goes to an
    instance if it lies within an error box of the same rule of the
    instance's cell. Category names are the rule ids that end magic's rule
    descriptions.

    Args:
        filename: Path to the error list.
        report: Existing DrcReport to append parsed violations into. The
            checked Layout is taken from report.ref_layout.
        directory: Optional Directory that named the cells in the GDS file
            (write_gds). Without it, the violations of the top cell are
            attached to it flat.
    """
    dbu_per_um = R('1u') / report.ref_layout.ref_layers.unit

    def conv(value_um: str) -> int:
        return int(round(float(value_um) * float(dbu_per_um)))

    errors = {}
    for line in Path(filename).read_text().splitlines():
        cell_name, why, box = line.split('\t')
        errors.setdefault(cell_name, []).append((why, Rect4I(*(conv(v) for v in box.split()))))

    def instances(layout):
        # The layouts and transforms of the instances, as in flatten_instance.
        for inst in layout.all(LayoutInstance):
            yield inst.ref, inst.loc_transform()
        for inst in layout.all(LayoutInstanceArray):
            for col in range(inst.cols):
                for row in range(inst.rows):
                    yield inst.ref, (col*inst.vec_col).transl() * (row*inst.vec_row).transl() * inst.loc_transform()

    category_by_name = {cat.name: cat for cat in report.all(DrcCategory)}
    # DrcCells are deduplicated across parse_drc calls, like categories.
    cell_by_name = {c.name: c for c in report.all(DrcCell)}
    queue = [(report.top_cell_name, report.ref_layout)]
    seen = {report.top_cell_name}
    while queue:
        cell_name, layout = queue.pop()
        below = []
        if directory is not None:
            for ref, tran in instances(layout):
                ref_name = directory.name_subgraph(ref)
                below += [(why, tran * rect) for why, rect in errors.get(ref_name, [])]
                if ref_name not in seen:
                    seen.add(ref_name)
                    queue.append((ref_name, ref))
        for why, rect in errors.get(cell_name, []):
            if any(why == b_why and rect.southwest in b_rect and rect.northeast in b_rect
                    for b_why, b_rect in below):
                continue
            m = re.search(r'\(([^()]*)\)$', why)
            rule = m.group(1) if m else why
            if rule not in category_by_name:
                category_by_name[rule] = report % DrcCategory(name=rule, description=why)
            if cell_name not in cell_by_name:
                cell_by_name[cell_name] = report % DrcCell(name=cell_name, ref_layout=layout)
            item = report % DrcItem(category=category_by_name[rule], cell=cell_by_name[cell_name])
            report % DrcBox(item=item, rect=rect)
