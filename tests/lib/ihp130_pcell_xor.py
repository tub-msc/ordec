# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
"""
KLayout batch script (klayout -b -r): generate SG13G2 PCells and XOR them
against ORDeC layouts.

Script variables (-rd):
    pdk_root: ihp-sg13g2 directory of the IHP Open PDK
    cases: JSON file, a list of {"id", "pcell", "params", "gds"}
    result_file: JSON file to write, per case id {"layer/datatype": XOR area
        in um²}

The layouts are flattened and aligned on the centers of their bounding
boxes. Text shapes are ignored.
"""

import json
import sys

import pya

python_dir = f"{pdk_root}/libs.tech/klayout/python"
sys.path[:0] = [python_dir, f"{python_dir}/pycell4klayout-api/source/python"]
import sg13g2_pycell_lib  # registers the library SG13_dev


def regions(layout):
    top = layout.top_cells()[0]
    result = {}
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        region = pya.Region(top.begin_shapes_rec(li))
        if not region.is_empty():
            key = f"{info.layer}/{info.datatype}"
            result[key] = (result.get(key, pya.Region()) + region).merged()
    return result


def bbox_center(regions):
    box = pya.Box()
    for region in regions.values():
        box += region.bbox()
    return box.center()


result = {}
for case in json.load(open(cases)):
    pdk_layout = pya.Layout()
    pdk_layout.dbu = 0.001
    top = pdk_layout.create_cell("top")
    pcell = pdk_layout.create_cell(case["pcell"], "SG13_dev", case["params"])
    top.insert(pya.CellInstArray(pcell.cell_index(), pya.Trans()))

    ordec_layout = pya.Layout()
    ordec_layout.read(case["gds"])

    a, b = regions(ordec_layout), regions(pdk_layout)
    ca, cb = bbox_center(a), bbox_center(b)
    shift = pya.Vector(cb.x - ca.x, cb.y - ca.y)
    diffs = {}
    for key in set(a) | set(b):
        xor = a.get(key, pya.Region()).moved(shift) ^ b.get(key, pya.Region())
        if not xor.is_empty():
            diffs[key] = xor.area() * 1e-6
    result[case["id"]] = diffs

json.dump(result, open(result_file, "w"), indent=1)
